from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from VIPMUSIC import app
from VIPMUSIC.misc import SUDOERS
from VIPMUSIC.utils.cookie_handler import download_cookies


@app.on_message(filters.command(["updatecookies", "updatecookie", "getc"]) & SUDOERS)
async def update_cookies(client, message: Message):
    url = message.command[1] if len(message.command) > 1 else config.COOKIES_URL
    if not url:
        return await message.reply_text("Set COOKIES_URL first or pass a supported HTTPS URL.")
    status = await message.reply_text("Downloading cookies...")
    try:
        path = await download_cookies(url)
        await status.edit_text(f"✅ Cookies updated and saved to <code>{path}</code>")
    except Exception as exc:
        await status.edit_text(f"❌ Cookie update failed: <code>{exc}</code>")


__MODULE__ = "Cookies"
__HELP__ = """**Cookie updater**

Owner/sudo command: `/updatecookies [HTTPS Gist/Pastebin/Batbin URL]`
"""
