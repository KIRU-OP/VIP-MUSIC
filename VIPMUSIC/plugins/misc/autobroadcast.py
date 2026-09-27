import asyncio

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from VIPMUSIC import app
from VIPMUSIC.utils.database import get_served_chats


async def _broadcast_once():
    chats = await get_served_chats()
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Add me to your group", url=f"https://t.me/{app.username}?startgroup=true")]])
    for chat in chats:
        chat_id = chat.get("chat_id")
        if isinstance(chat_id, int):
            try:
                await app.send_message(chat_id, config.AUTO_GCAST_MSG or "🎵 Music bot is online. Use /help to see commands.", reply_markup=markup)
                await asyncio.sleep(2)
            except Exception:
                continue


async def _broadcast_loop():
    await asyncio.sleep(10)
    while str(config.AUTO_GCAST).lower() == "on":
        await _broadcast_once()
        await asyncio.sleep(100000)


if str(config.AUTO_GCAST).lower() == "on":
    asyncio.create_task(_broadcast_loop())
