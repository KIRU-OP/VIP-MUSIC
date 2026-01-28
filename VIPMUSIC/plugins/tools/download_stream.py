import asyncio
import os
import time
import wget
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from yt_dlp import YoutubeDL

from VIPMUSIC import app
# Humne aapki naya YouTubeAPI class import kar liya
from VIPMUSIC.platforms.Youtube import YouTubeAPI

# Initialize YouTube API
YouTube = YouTubeAPI()

# User trackers
user_last_CallbackQuery_time = {}
user_CallbackQuery_count = {}

# Spam config
SPAM_WINDOW_SECONDS = 30
BANNED_USERS = []

@app.on_callback_query(filters.regex("downloadvideo") & ~filters.user(BANNED_USERS))
async def download_video(client, CallbackQuery):
    user_id = CallbackQuery.from_user.id
    current_time = time.time()

    last_Query_time = user_last_CallbackQuery_time.get(user_id, 0)
    if current_time - last_Query_time < SPAM_WINDOW_SECONDS:
        await CallbackQuery.answer(
            "➻ ʏᴏᴜ ʜᴀᴠᴇ ʜᴀᴠᴇ ᴀʟʀᴇᴀᴅʏ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ ʏᴏᴜʀ ᴠɪᴅᴇᴏ.\n\n➥ ɴᴇxᴛ sᴏɴɢ ᴅᴏᴡɴʟᴏᴀᴅ ᴀғᴛᴇʀ 30 sᴇᴄᴏɴᴅs.",
            show_alert=True,
        )
        return
    
    user_last_CallbackQuery_time[user_id] = current_time
    callback_data = CallbackQuery.data.strip()
    videoid = callback_data.split(None, 1)[1]
    user_name = CallbackQuery.from_user.first_name
    mention = f"[{user_name}](tg://user?id={user_id})"

    await CallbackQuery.answer("ᴏᴋ sɪʀ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...", show_alert=True)
    pablo = await client.send_message(
        CallbackQuery.message.chat.id,
        f"**ʜᴇʏ {mention} ᴅᴏᴡɴʟᴏᴅɪɴɢ ʏᴏᴜʀ ᴠɪᴅᴇᴏ, ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...**",
    )

    # API V3 se details nikalna (No Cookies used here)
    details = await YouTube.details(videoid, videoid=True)
    if not details:
        await pablo.edit(f"**ʜᴇʏ {mention} ʏᴏᴜʀ sᴏɴɢ ɴᴏᴛ ғᴏᴜɴᴅ ᴏɴ ʏᴏᴜᴛᴜʙᴇ.**")
        return

    title, duration_min, duration_sec, thumbnail, vidid = details
    url = f"https://www.youtube.com/watch?v={vidid}"
    
    try:
        sedlyf = wget.download(thumbnail)
    except:
        sedlyf = None

    opts = {
        "format": "best",
        "addmetadata": True,
        "key": "FFmpegMetadata",
        "prefer_ffmpeg": True,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
        "outtmpl": "%(id)s.mp4",
        "logtostderr": False,
        "quiet": True,
        # Cookies removed from here
    }

    try:
        with YoutubeDL(opts) as ytdl:
            ytdl_data = await asyncio.to_thread(ytdl.extract_info, url, download=True)
    except Exception as e:
        await pablo.edit(f"**ғᴀɪʟᴇᴅ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ.**\n**ᴇʀʀᴏʀ:** `{str(e)}` ")
        return

    file_stark = f"{ytdl_data['id']}.mp4"
    capy = f"❄ **ᴛɪᴛʟᴇ :** [{title}]({url})\n\n🥀 **ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ :** {mention}"
    
    try:
        await client.send_video(
            CallbackQuery.from_user.id,
            video=open(file_stark, "rb"),
            duration=duration_sec,
            file_name=title,
            thumb=sedlyf,
            caption=capy,
            supports_streaming=True,
        )
        await client.send_message(
            CallbackQuery.message.chat.id,
            f"**ʜᴇʏ** {mention}\n**✅ ᴠɪᴅᴇᴏ sᴇɴᴛ ɪɴ ʏᴏᴜʀ ᴘᴍ/ᴅᴍ.**",
        )
        await pablo.delete()
    except Exception:
        await pablo.delete()
        await client.send_message(
            CallbackQuery.message.chat.id,
            f"**ʜᴇʏ {mention} ᴘʟᴇᴀsᴇ ᴜɴʙʟᴏᴄᴋ ᴍᴇ ɪɴ ᴘᴍ.**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👉 ᴜɴʙʟᴏᴄᴋ ᴍᴇ", url=f"https://t.me/{app.username}?start=info_{vidid}")]])
        )
    finally:
        if sedlyf and os.path.exists(sedlyf): os.remove(sedlyf)
        if os.path.exists(file_stark): os.remove(file_stark)


@app.on_callback_query(filters.regex("downloadaudio") & ~filters.user(BANNED_USERS))
async def download_audio(client, CallbackQuery):
    user_id = CallbackQuery.from_user.id
    current_time = time.time()

    last_Query_time = user_last_CallbackQuery_time.get(user_id, 0)
    if current_time - last_Query_time < SPAM_WINDOW_SECONDS:
        await CallbackQuery.answer("➻ ɴᴇxᴛ sᴏɴɢ ᴅᴏᴡɴʟᴏᴀᴅ ᴀғᴛᴇʀ 30 sᴇᴄᴏɴᴅs.", show_alert=True)
        return

    user_last_CallbackQuery_time[user_id] = current_time
    callback_data = CallbackQuery.data.strip()
    videoid = callback_data.split(None, 1)[1]
    user_name = CallbackQuery.from_user.first_name
    mention = f"[{user_name}](tg://user?id={user_id})"

    await CallbackQuery.answer("ᴏᴋ sɪʀ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴀᴜᴅɪᴏ...", show_alert=True)
    pablo = await client.send_message(CallbackQuery.message.chat.id, f"**ʜᴇʏ {mention} ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴀᴜᴅɪᴏ...**")

    # API V3 Details
    details = await YouTube.details(videoid, videoid=True)
    if not details:
        await pablo.edit(f"**ʜᴇʏ {mention} sᴏɴɢ ɴᴏᴛ ғᴏᴜɴᴅ.**")
        return

    title, duration_min, duration_sec, thumbnail, vidid = details
    url = f"https://www.youtube.com/watch?v={vidid}"
    
    try:
        sedlyf = wget.download(thumbnail)
    except:
        sedlyf = None

    opts = {
        "format": "bestaudio/best",
        "addmetadata": True,
        "key": "FFmpegMetadata",
        "prefer_ffmpeg": True,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "outtmpl": "%(id)s.mp3",
        "quiet": True,
        # Cookies removed
    }

    try:
        with YoutubeDL(opts) as ytdl:
            ytdl_data = await asyncio.to_thread(ytdl.extract_info, url, download=True)
    except Exception as e:
        await pablo.edit(f"**ғᴀɪʟᴇᴅ.** \n`{str(e)}`")
        return

    file_stark = f"{ytdl_data['id']}.mp3"
    capy = f"❄ **ᴛɪᴛʟᴇ :** [{title}]({url})\n🥀 **ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ :** {mention}\n⏳ **ᴅᴜʀᴀᴛɪᴏɴ :** {duration_min}"

    try:
        await client.send_audio(
            CallbackQuery.from_user.id,
            audio=open(file_stark, "rb"),
            title=title,
            thumb=sedlyf,
            caption=capy,
        )
        await client.send_message(CallbackQuery.message.chat.id, f"**ʜᴇʏ {mention} ✅ ᴀᴜᴅɪᴏ sᴇɴᴛ ɪɴ ᴘᴍ.**")
        await pablo.delete()
    except Exception:
        await pablo.delete()
        await client.send_message(CallbackQuery.message.chat.id, f"**ʜᴇʏ {mention} ᴘʟᴇᴀsᴇ ᴜɴʙʟᴏᴄᴋ ᴍᴇ.**")
    finally:
        if sedlyf and os.path.exists(sedlyf): os.remove(sedlyf)
        if os.path.exists(file_stark): os.remove(file_stark)
