import asyncio
import os
import time

import aiohttp
import wget
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from youtubesearchpython import SearchVideos

from VIPMUSIC import app

# ----------------------------------------------------------------------------
# Spam-tracking (kept SEPARATE for video vs audio - the original shared one
# dict, which meant downloading a video also blocked audio downloads for the
# same user and vice versa)
# ----------------------------------------------------------------------------
user_last_video_query_time = {}
user_last_audio_query_time = {}
user_CallbackQuery_count = {}

SPAM_WINDOW_SECONDS = 30
SPAM_AUDIO_WINDOW_SECONDS = 30
BANNED_USERS = []

# ----------------------------------------------------------------------------
# Download API cascade: Primary -> Fallback (token based) -> Worker
# NOTE: All three are third-party/self-run services outside Anthropic's
# control. I have not verified any of these are currently live or that
# their response shapes match the comments below - treat these as your
# best-known contract and adjust parsing if a real response differs.
#
# SECURITY: move SHRUTI_API_KEY to an environment variable like the worker
# key below, rather than hardcoding it here. If this key has already been
# shared/pasted elsewhere, rotate it.
# ----------------------------------------------------------------------------
SHRUTI_API_KEY = os.environ.get("SHRUTI_API_KEY", "ShrutiBotsPAVXJFsXdDeoJqDOe4NW")
PRIMARY_API_URL = "https://api.shrutibots.site"

FALLBACK_API_URL = "http://13.212.126.0:2020"

WORKER_FALLBACK_API_URL = os.environ.get(
    "WORKER_FALLBACK_API_URL", "https://youtubenewapi.skybotsdeveloper.workers.dev"
)
WORKER_FALLBACK_API_KEY = os.environ.get("WORKER_FALLBACK_API_KEY", "itsmesid")

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)


async def _stream_response_to_file(resp: aiohttp.ClientResponse, dest_path: str) -> str:
    with open(dest_path, "wb") as f:
        async for chunk in resp.content.iter_chunked(1024 * 256):
            f.write(chunk)
    return dest_path


async def _try_primary(video_url: str, media_type: str, dest_path: str) -> str:
    """
    Primary Shruti API - direct download.
    GET /download?url={video_url}&type={media_type}&api_key={KEY}
    """
    params = {"url": video_url, "type": media_type, "api_key": SHRUTI_API_KEY}
    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
        async with session.get(f"{PRIMARY_API_URL}/download", params=params) as resp:
            if resp.status != 200:
                raise Exception(f"primary API HTTP {resp.status}: {await resp.text()}")
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                raise Exception(f"primary API returned JSON, not a file: {await resp.text()}")
            return await _stream_response_to_file(resp, dest_path)


async def _try_fallback(video_url: str, video_id: str, media_type: str, dest_path: str) -> str:
    """
    Legacy/fallback API - two step, token based.
    Step 1: GET /download?url={video_url}&type={media_type} -> {"download_token": "xxx"}
    Step 2: GET /stream/{video_id}?type={media_type}  header X-Download-Token: token
    """
    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
        params = {"url": video_url, "type": media_type}
        async with session.get(f"{FALLBACK_API_URL}/download", params=params) as resp:
            if resp.status != 200:
                raise Exception(f"fallback API (token step) HTTP {resp.status}: {await resp.text()}")
            data = await resp.json()
            token = data.get("download_token")
            if not token:
                raise Exception(f"fallback API did not return a download_token: {data}")

        headers = {"X-Download-Token": token}
        stream_params = {"type": media_type}
        async with session.get(
            f"{FALLBACK_API_URL}/stream/{video_id}", headers=headers, params=stream_params
        ) as resp:
            if resp.status != 200:
                raise Exception(f"fallback API (stream step) HTTP {resp.status}: {await resp.text()}")
            return await _stream_response_to_file(resp, dest_path)


async def _try_worker(video_url: str, media_type: str, dest_path: str) -> str:
    """
    Cloudflare worker fallback - direct download.
    GET /download?url={video_url}&type={media_type}&key={KEY}
    """
    params = {"url": video_url, "type": media_type, "key": WORKER_FALLBACK_API_KEY}
    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
        async with session.get(f"{WORKER_FALLBACK_API_URL}/download", params=params) as resp:
            if resp.status != 200:
                raise Exception(f"worker API HTTP {resp.status}: {await resp.text()}")
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                raise Exception(f"worker API returned JSON, not a file: {await resp.text()}")
            return await _stream_response_to_file(resp, dest_path)


async def fetch_media(video_url: str, video_id: str, media_type: str, dest_path: str) -> str:
    """
    Tries Primary -> Fallback -> Worker in order. Returns the local file path
    of the first one that succeeds. Raises Exception with all three errors
    combined if every provider fails.
    """
    errors = []

    for name, coro in (
        ("primary", _try_primary(video_url, media_type, dest_path)),
        ("fallback", _try_fallback(video_url, video_id, media_type, dest_path)),
        ("worker", _try_worker(video_url, media_type, dest_path)),
    ):
        try:
            return await coro
        except Exception as e:
            errors.append(f"[{name}] {e}")
            if os.path.exists(dest_path):
                os.remove(dest_path)

    raise Exception(" | ".join(errors))


# ----------------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------------
@app.on_callback_query(filters.regex("downloadvideo") & ~filters.user(BANNED_USERS))
async def download_video(client, CallbackQuery):
    user_id = CallbackQuery.from_user.id
    current_time = time.time()

    last_query_time = user_last_video_query_time.get(user_id, 0)
    if current_time - last_query_time < SPAM_WINDOW_SECONDS:
        await CallbackQuery.answer(
            "➻ ʏᴏᴜ ʜᴀᴠᴇ ᴀʟʀᴇᴀᴅʏ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ ʏᴏᴜʀ ᴠɪᴅᴇᴏ (ᴄʜᴇᴄᴋ ᴍʏ ᴅᴍ/ᴘᴍ).\n\n➥ ɴᴇxᴛ sᴏɴɢ ᴅᴏᴡɴʟᴏᴀᴅ ᴀғᴛᴇʀ 30 sᴇᴄᴏɴᴅs.",
            show_alert=True,
        )
        return

    user_last_video_query_time[user_id] = current_time
    user_CallbackQuery_count[user_id] = user_CallbackQuery_count.get(user_id, 0) + 1

    callback_data = CallbackQuery.data.strip()
    videoid = callback_data.split(None, 1)[1]
    user_name = CallbackQuery.from_user.first_name
    mention = f"[{user_name}](tg://user?id={user_id})"

    await CallbackQuery.answer("ᴏᴋ sɪʀ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...", show_alert=True)
    pablo = await client.send_message(
        CallbackQuery.message.chat.id,
        f"**ʜᴇʏ {mention} ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ʏᴏᴜʀ ᴠɪᴅᴇᴏ, ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...**",
    )

    search = SearchVideos(f"https://youtube.com/{videoid}", offset=1, mode="dict", max_results=1)
    mi = search.result()
    mio = mi.get("search_result", [])
    if not mio:
        await pablo.edit(f"**ʜᴇʏ {mention} ʏᴏᴜʀ sᴏɴɢ ɴᴏᴛ ғᴏᴜɴᴅ ᴏɴ ʏᴏᴜᴛᴜʙᴇ.**")
        return

    mo = mio[0].get("link", "")
    title = mio[0].get("title", "")
    video_id = mio[0].get("id", "")
    channel = mio[0].get("channel", "")
    thumb_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

    await asyncio.sleep(0.6)
    try:
        thumb_path = wget.download(thumb_url)
    except Exception:
        thumb_path = None

    file_path = f"{video_id}.mp4"
    try:
        await fetch_media(mo, video_id, "video", file_path)
    except Exception as e:
        await pablo.edit(f"**ʜᴇʏ {mention} ғᴀɪʟᴇᴅ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ.** \n**ᴇʀʀᴏʀ:** `{str(e)}`")
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
        return

    caption = (
        f"❄ **ᴛɪᴛʟᴇ :** [{title}]({mo})\n\n"
        f"💫 **ᴄʜᴀɴɴᴇʟ :** {channel}\n\n"
        f"🥀 **ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ :** {mention}"
    )
    try:
        await client.send_video(
            CallbackQuery.from_user.id,
            video=file_path,
            file_name=title,
            thumb=thumb_path,
            caption=caption,
            supports_streaming=True,
        )
        await pablo.delete()
    except Exception:
        await pablo.delete()
        await client.send_message(
            CallbackQuery.message.chat.id,
            f"**ʜᴇʏ {mention} ᴘʟᴇᴀsᴇ ᴜɴʙʟᴏᴄᴋ ᴍᴇ ɪɴ ᴘᴍ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ᴛʜᴇ ᴠɪᴅᴇᴏ.**",
        )
    finally:
        for f in (thumb_path, file_path):
            if f and os.path.exists(f):
                os.remove(f)


@app.on_callback_query(filters.regex("downloadaudio") & ~filters.user(BANNED_USERS))
async def download_audio(client, CallbackQuery):
    user_id = CallbackQuery.from_user.id
    current_time = time.time()

    last_query_time = user_last_audio_query_time.get(user_id, 0)
    if current_time - last_query_time < SPAM_AUDIO_WINDOW_SECONDS:
        await CallbackQuery.answer(
            "➻ ʏᴏᴜ ʜᴀᴠᴇ ᴀʟʀᴇᴀᴅʏ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ ʏᴏᴜʀ ᴀᴜᴅɪᴏ (ᴄʜᴇᴄᴋ ᴍʏ ᴅᴍ/ᴘᴍ).\n\n➥ ɴᴇxᴛ sᴏɴɢ ᴅᴏᴡɴʟᴏᴀᴅ ᴀғᴛᴇʀ 30 sᴇᴄᴏɴᴅs.",
            show_alert=True,
        )
        return

    user_last_audio_query_time[user_id] = current_time
    user_CallbackQuery_count[user_id] = user_CallbackQuery_count.get(user_id, 0) + 1

    callback_data = CallbackQuery.data.strip()
    videoid = callback_data.split(None, 1)[1]
    user_name = CallbackQuery.from_user.first_name
    mention = f"[{user_name}](tg://user?id={user_id})"

    await CallbackQuery.answer("ᴏᴋ sɪʀ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...", show_alert=True)
    pablo = await client.send_message(
        CallbackQuery.message.chat.id,
        f"**ʜᴇʏ {mention} ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ʏᴏᴜʀ ᴀᴜᴅɪᴏ, ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...**",
    )

    search = SearchVideos(f"https://youtube.com/{videoid}", offset=1, mode="dict", max_results=1)
    mi = search.result()
    mio = mi.get("search_result", [])
    if not mio:
        await pablo.edit(f"**ʜᴇʏ {mention} ʏᴏᴜʀ sᴏɴɢ ɴᴏᴛ ғᴏᴜɴᴅ ᴏɴ ʏᴏᴜᴛᴜʙᴇ.**")
        return

    mo = mio[0].get("link", "")
    title = mio[0].get("title", "")
    video_id = mio[0].get("id", "")
    channel = mio[0].get("channel", "")
    thumb_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

    await asyncio.sleep(0.6)
    try:
        thumb_path = wget.download(thumb_url)
    except Exception:
        thumb_path = None

    file_path = f"{video_id}.mp3"
    try:
        await fetch_media(mo, video_id, "audio", file_path)
    except Exception as e:
        await pablo.edit(f"**ʜᴇʏ {mention} ғᴀɪʟᴇᴅ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ.** \n**ᴇʀʀᴏʀ:** `{str(e)}`")
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
        return

    caption = (
        f"❄ **ᴛɪᴛʟᴇ :** [{title}]({mo})\n\n"
        f"💫 **ᴄʜᴀɴɴᴇʟ :** {channel}\n\n"
        f"🥀 **ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ :** {mention}"
    )
    try:
        await client.send_audio(
            CallbackQuery.from_user.id,
            audio=file_path,
            title=title,
            thumb=thumb_path,
            caption=caption,
        )
        await pablo.delete()
    except Exception:
        await pablo.delete()
        await client.send_message(
            CallbackQuery.message.chat.id,
            f"**ʜᴇʏ {mention} ᴘʟᴇᴀsᴇ ᴜɴʙʟᴏᴄᴋ ᴍᴇ ɪɴ ᴘᴍ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ᴛʜᴇ ᴀᴜᴅɪᴏ.**",
        )
    finally:
        for f in (thumb_path, file_path):
            if f and os.path.exists(f):
                os.remove(f)
