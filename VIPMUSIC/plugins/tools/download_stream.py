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
# Spam-tracking (kept SEPARATE for video vs audio, unlike the original which
# shared one dict and accidentally rate-limited both together)
# ----------------------------------------------------------------------------
user_last_video_query_time = {}
user_last_audio_query_time = {}
user_CallbackQuery_count = {}

SPAM_WINDOW_SECONDS = 30
SPAM_AUDIO_WINDOW_SECONDS = 30
BANNED_USERS = []

# ----------------------------------------------------------------------------
# cobalt.tools public API
# Docs (subject to change): https://github.com/imputnet/cobalt
# NOTE: This is a third-party free API. It can go down, rate-limit you, or
# change its response shape without notice. Test it before relying on it.
# If it stops working, you'll need to swap COBALT_API_URL for a different
# provider (self-hosted cobalt instance, RapidAPI downloader, etc.) and
# adjust `cobalt_request()` to match that provider's request/response format.
# ----------------------------------------------------------------------------
COBALT_API_URL = "https://api.cobalt.tools/api/json"


async def cobalt_request(youtube_url: str, audio_only: bool) -> dict:
    """
    Calls the cobalt.tools API and returns its parsed JSON response.
    Raises Exception on network/API errors.
    """
    payload = {
        "url": youtube_url,
        "isAudioOnly": audio_only,
        "aFormat": "mp3",
        "vCodec": "h264",
        "vQuality": "720",
        "filenamePattern": "basic",
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            COBALT_API_URL, json=payload, headers=headers, timeout=30
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"cobalt API returned HTTP {resp.status}: {text}")
            data = await resp.json()

    status = data.get("status")
    if status in ("error", "rate-limit"):
        raise Exception(f"cobalt API error: {data.get('text', data)}")
    if status not in ("stream", "redirect", "picker"):
        raise Exception(f"Unexpected cobalt API response: {data}")

    return data


async def cobalt_download_url(youtube_url: str, audio_only: bool) -> str:
    """
    Returns a direct, downloadable media URL for the given YouTube link.
    """
    data = await cobalt_request(youtube_url, audio_only)

    if data["status"] == "picker":
        # Multiple options returned (e.g. separate audio/video streams) -
        # just take the first one.
        picks = data.get("picker", [])
        if not picks:
            raise Exception("cobalt API returned an empty picker list")
        return picks[0]["url"]

    return data["url"]


async def download_file(url: str, dest_path: str) -> str:
    """
    Streams `url` to `dest_path` using aiohttp (async, non-blocking).
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=None)) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch file, HTTP {resp.status}")
            with open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 256):
                    f.write(chunk)
    return dest_path


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
        direct_url = await cobalt_download_url(mo, audio_only=False)
        await download_file(direct_url, file_path)
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
        direct_url = await cobalt_download_url(mo, audio_only=True)
        await download_file(direct_url, file_path)
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
