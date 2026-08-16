#
# Copyright (C) 2024 by THE-VIP-BOY-OP@Github, < https://github.com/THE-VIP-BOY-OP >.
#
# This file is part of < https://github.com/THE-VIP-BOY-OP/VIP-MUSIC > project,
# and is released under the MIT License.
# Please see < https://github.com/THE-VIP-BOY-OP/VIP-MUSIC/blob/master/LICENSE >
#
# All rights reserved.
#

import re
from math import ceil
from typing import Union

from pyrogram import filters, types
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import BANNED_USERS, START_IMG_URL
from strings import get_command, get_string
from VIPMUSIC import HELPABLE, app
from VIPMUSIC.utils.database import get_lang, is_commanddelete_on
from VIPMUSIC.utils.decorators.language import LanguageStart
from VIPMUSIC.utils.inline.help import private_help_panel

# ─────────────────────────────────────────
#  ᴄᴏᴍᴍᴀɴᴅ
# ─────────────────────────────────────────
HELP_COMMAND = get_command("HELP_COMMAND")

COLUMN_SIZE = 4   # ʀᴏᴡs ᴘᴇʀ ᴘᴀɢᴇ
NUM_COLUMNS = 3   # ᴄᴏʟᴜᴍɴs ᴘᴇʀ ʀᴏᴡ

# ─────────────────────────────────────────
#  ꜱᴍᴀʟʟ ᴄᴀᴘs ꜰᴏɴᴛ ᴄᴏɴᴠᴇʀᴛᴇʀ
# ─────────────────────────────────────────
NORMAL_TO_SMALL_CAPS = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ',
    'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ',
    'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ',
    's': 's', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
    'y': 'ʏ', 'z': 'ᴢ',
    'A': 'ᴀ', 'B': 'ʙ', 'C': 'ᴄ', 'D': 'ᴅ', 'E': 'ᴇ', 'F': 'ꜰ',
    'G': 'ɢ', 'H': 'ʜ', 'I': 'ɪ', 'J': 'ᴊ', 'K': 'ᴋ', 'L': 'ʟ',
    'M': 'ᴍ', 'N': 'ɴ', 'O': 'ᴏ', 'P': 'ᴘ', 'Q': 'ǫ', 'R': 'ʀ',
    'S': 's', 'T': 'ᴛ', 'U': 'ᴜ', 'V': 'ᴠ', 'W': 'ᴡ', 'X': 'x',
    'Y': 'ʏ', 'Z': 'ᴢ',
}

# ─────────────────────────────────────────
#  ᴍᴏᴅᴜʟᴇ ɪᴄᴏɴ ᴍᴀᴘ  (ᴄᴜsᴛᴏᴍɪᴢᴇ ᴀs ɴᴇᴇᴅᴇᴅ)
# ─────────────────────────────────────────
MODULE_ICONS = {
    "play":      "▶️",
    "queue":     "📋",
    "admin":     "⚙️",
    "stats":     "📊",
    "settings":  "🛠️",
    "sudo":      "👑",
    "download":  "⬇️",
    "language":  "🌐",
    "loop":      "🔁",
    "seek":      "⏩",
    "filter":    "🎛️",
    "broadcast": "📢",
    "ban":       "🚫",
    "auth":      "🔑",
    "channel":   "📡",
    "speed":     "💨",
    "lyrics":    "🎤",
    "ping":      "🏓",
    "help":      "❓",
}

DEFAULT_ICON = ""


def to_small_caps(text: str) -> str:
    return "".join(NORMAL_TO_SMALL_CAPS.get(c, c) for c in text)


def get_module_icon(module_name: str) -> str:
    return MODULE_ICONS.get(module_name.lower(), DEFAULT_ICON)


# ─────────────────────────────────────────
#  ᴄᴜsᴛᴏᴍ ʙᴜᴛᴛᴏɴ ᴄʟᴀss
# ─────────────────────────────────────────
class EqInlineKeyboardButton(InlineKeyboardButton):
    def __eq__(self, other):
        return self.text == other.text

    def __lt__(self, other):
        return self.text < other.text

    def __gt__(self, other):
        return self.text > other.text


# ─────────────────────────────────────────
#  ᴘᴀɢɪɴᴀᴛɪᴏɴ ᴇɴɢɪɴᴇ
# ─────────────────────────────────────────
def paginate_modules(
    page_n: int,
    module_dict: dict,
    prefix: str,
    chat=None,
    close: bool = False,
):
    """
    ᴍᴏᴅᴜʟᴇs ᴋᴏ A→Z ꜱᴏʀᴛ ᴋᴀʀᴋᴇ ɪɴʟɪɴᴇ ʙᴜᴛᴛᴏɴs ʙɴᴀᴏ.
    ʜᴀʀ ʙᴜᴛᴛᴏɴ ᴘᴇ ɪᴄᴏɴ + ꜱᴍᴀʟʟᴄᴀᴘs ɴᴀᴍᴇ ᴅɪᴋʜᴇɢᴀ.
    """
    sorted_modules = sorted(
        module_dict.values(), key=lambda x: x.__MODULE__.lower()
    )

    def make_button(mod, pg):
        icon = get_module_icon(mod.__MODULE__)
        label = f"{icon} {to_small_caps(mod.__MODULE__)}"
        mod_lower = mod.__MODULE__.lower()
        if chat:
            cb = f"{prefix}_module({chat},{mod_lower},{pg})"
        else:
            cb = f"{prefix}_module({mod_lower},{pg})"
        return EqInlineKeyboardButton(label, callback_data=cb)

    modules = [make_button(x, page_n) for x in sorted_modules]

    pairs = [
        modules[i: i + NUM_COLUMNS]
        for i in range(0, len(modules), NUM_COLUMNS)
    ]

    max_num_pages = ceil(len(pairs) / COLUMN_SIZE) if pairs else 1
    modulo_page = page_n % max_num_pages

    # ─── ᴍᴜʟᴛɪᴘʟᴇ ᴘᴀɢᴇs ───
    if len(pairs) > COLUMN_SIZE:
        current_pairs = pairs[
            modulo_page * COLUMN_SIZE: COLUMN_SIZE * (modulo_page + 1)
        ]

        updated_pairs = []
        for row in current_pairs:
            updated_row = []
            for btn in row:
                m = re.search(r"_module\((.+?),", btn.callback_data)
                mod_name = m.group(1) if m else btn.text.lower()
                if chat:
                    cb = f"{prefix}_module({chat},{mod_name},{modulo_page})"
                else:
                    cb = f"{prefix}_module({mod_name},{modulo_page})"
                updated_row.append(
                    EqInlineKeyboardButton(btn.text, callback_data=cb)
                )
            updated_pairs.append(updated_row)

        # ─── ɴᴀᴠɪɢᴀᴛɪᴏɴ ʀᴏᴡ ───
        prev_page = modulo_page - 1 if modulo_page > 0 else max_num_pages - 1
        updated_pairs.append([
            EqInlineKeyboardButton(
                "❮",
                callback_data=f"{prefix}_prev({prev_page})",
            ),
            EqInlineKeyboardButton(
                "✖️ ᴄʟᴏsᴇ" if close else "↩️ ʙᴀᴄᴋ",
                callback_data="close" if close else "settingsback_helper",
            ),
            EqInlineKeyboardButton(
                "❯",
                callback_data=f"{prefix}_next({modulo_page + 1})",
            ),
        ])
        return updated_pairs

    # ─── ꜱɪɴɢʟᴇ ᴘᴀɢᴇ ───
    pairs.append([
        EqInlineKeyboardButton(
            "✖️ ᴄʟᴏsᴇ" if close else "↩️ ʙᴀᴄᴋ",
            callback_data="close" if close else "settingsback_helper",
        ),
    ])
    return pairs


# ─────────────────────────────────────────
#  /help  ᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛ
# ─────────────────────────────────────────
@app.on_message(filters.command(HELP_COMMAND) & filters.private & ~BANNED_USERS)
@app.on_callback_query(filters.regex("settings_back_helper") & ~BANNED_USERS)
async def helper_private(
    client: app,
    update: Union[types.Message, types.CallbackQuery],
):
    is_callback = isinstance(update, types.CallbackQuery)

    if is_callback:
        try:
            await update.answer()
        except Exception:
            pass
        chat_id = update.message.chat.id
        language = await get_lang(chat_id)
        _ = get_string(language)
        keyboard = InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "help"))
        await update.edit_message_text(_["help_1"], reply_markup=keyboard)

    else:
        chat_id = update.chat.id
        if await is_commanddelete_on(chat_id):
            try:
                await update.delete()
            except Exception:
                pass

        language = await get_lang(chat_id)
        _ = get_string(language)
        keyboard = InlineKeyboardMarkup(
            paginate_modules(0, HELPABLE, "help", close=True)
        )

        if START_IMG_URL:
            await update.reply_photo(
                photo=START_IMG_URL,
                caption=_["help_1"],
                reply_markup=keyboard,
            )
        else:
            await update.reply_text(
                text=_["help_1"],
                reply_markup=keyboard,
            )


# ─────────────────────────────────────────
#  /help  ɢʀᴏᴜᴘ ᴄʜᴀᴛ
# ─────────────────────────────────────────
@app.on_message(filters.command(HELP_COMMAND) & filters.group & ~BANNED_USERS)
@LanguageStart
async def help_com_group(client, message: Message, _):
    keyboard = private_help_panel(_)
    await message.reply_text(
        _["help_2"],
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─────────────────────────────────────────
#  ʜᴇʟᴘ ᴘᴀʀsᴇʀ ᴜᴛɪʟɪᴛʏ
# ─────────────────────────────────────────
async def help_parser(name, keyboard=None):
    if not keyboard:
        keyboard = InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "help"))
    return keyboard


# ─────────────────────────────────────────
#  ᴄᴀʟʟʙᴀᴄᴋ ʜᴀɴᴅʟᴇʀ
# ─────────────────────────────────────────
@app.on_callback_query(filters.regex(r"help_(.*?)"))
async def help_button(client, query):
    home_match  = re.match(r"help_home\((.+?)\)", query.data)
    mod_match   = re.match(r"help_module\((.+?),(.+?)\)", query.data)
    prev_match  = re.match(r"help_prev\((.+?)\)", query.data)
    next_match  = re.match(r"help_next\((.+?)\)", query.data)
    back_match  = re.match(r"help_back\((\d+)\)", query.data)
    create_match = re.match(r"help_create", query.data)

    language = await get_lang(query.message.chat.id)
    _ = get_string(language)
    top_text = _["help_1"]

    # ─── ᴍᴏᴅᴜʟᴇ ᴅᴇᴛᴀɪʟ ᴠɪᴇᴡ ───
    if mod_match:
        module = mod_match.group(1)
        prev_page_num = int(mod_match.group(2))

        icon = get_module_icon(module)
        mod_obj = HELPABLE.get(module)
        if not mod_obj:
            await query.answer("ᴍᴏᴅᴜʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ!", show_alert=True)
            return

        text = (
            f"<b>{icon} {to_small_caps(mod_obj.__MODULE__)}</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"{mod_obj.__HELP__}"
        )

        key = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "↩️ ʙᴀᴄᴋ",
                callback_data=f"help_back({prev_page_num})",
            ),
            InlineKeyboardButton(
                "✖️ ᴄʟᴏsᴇ",
                callback_data="close",
            ),
        ]])

        await query.message.edit(
            text=text,
            reply_markup=key,
            disable_web_page_preview=True,
        )

    # ─── ʜᴏᴍᴇ ───
    elif home_match:
        await app.send_message(
            query.from_user.id,
            text=top_text,
            reply_markup=InlineKeyboardMarkup(
                paginate_modules(0, HELPABLE, "help")
            ),
        )
        await query.message.delete()

    # ─── ᴘʀᴇᴠ ᴘᴀɢᴇ ───
    elif prev_match:
        curr_page = int(prev_match.group(1))
        await query.message.edit(
            text=top_text,
            reply_markup=InlineKeyboardMarkup(
                paginate_modules(curr_page, HELPABLE, "help")
            ),
            disable_web_page_preview=True,
        )

    # ─── ɴᴇxᴛ ᴘᴀɢᴇ ───
    elif next_match:
        next_page = int(next_match.group(1))
        await query.message.edit(
            text=top_text,
            reply_markup=InlineKeyboardMarkup(
                paginate_modules(next_page, HELPABLE, "help")
            ),
            disable_web_page_preview=True,
        )

    # ─── ʙᴀᴄᴋ ───
    elif back_match:
        prev_page_num = int(back_match.group(1))
        await query.message.edit(
            text=top_text,
            reply_markup=InlineKeyboardMarkup(
                paginate_modules(prev_page_num, HELPABLE, "help")
            ),
            disable_web_page_preview=True,
        )

    # ─── ᴄʀᴇᴀᴛᴇ ───
    elif create_match:
        await query.message.edit(
            text=top_text,
            reply_markup=InlineKeyboardMarkup(
                paginate_modules(0, HELPABLE, "help")
            ),
            disable_web_page_preview=True,
        )

    await client.answer_callback_query(query.id)
