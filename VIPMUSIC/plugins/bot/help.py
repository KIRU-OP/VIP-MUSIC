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

### Command Settings
HELP_COMMAND = get_command("HELP_COMMAND")

COLUMN_SIZE = 4  
NUM_COLUMNS = 3  

# Font transformation function (Normal to Small Caps 'ʜʟᴏ' style)
def get_small_caps(text):
    small_caps_map = {
        "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ғ", "g": "ɢ", "h": "ʜ",
        "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ", "o": "ᴏ", "p": "ᴘ",
        "q": "ǫ", "r": "ʀ", "s": "s", "t": "ᴛ", "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x",
        "y": "ʏ", "z": "ᴢ",
    }
    return "".join(small_caps_map.get(char.lower(), char) for char in text)

class EqInlineKeyboardButton(InlineKeyboardButton):
    def __eq__(self, other):
        return self.text == other.text

    def __lt__(self, other):
        return self.text < other.text

    def __gt__(self, other):
        return self.text > other.text


def paginate_modules(page_n, module_dict, prefix, chat=None, close: bool = False):
    if not chat:
        modules = sorted(
            [
                EqInlineKeyboardButton(
                    get_small_caps(x.__MODULE__), # RED CIRCLE AREA: Arrow removed, only Small Caps font
                    callback_data="{}_module({},{})".format(
                        prefix, x.__MODULE__.lower(), page_n
                    ),
                )
                for x in module_dict.values()
            ]
        )
    else:
        modules = sorted(
            [
                EqInlineKeyboardButton(
                    get_small_caps(x.__MODULE__), # RED CIRCLE AREA: Arrow removed, only Small Caps font
                    callback_data="{}_module({},{},{})".format(
                        prefix, chat, x.__MODULE__.lower(), page_n
                    ),
                )
                for x in module_dict.values()
            ]
        )

    pairs = [modules[i : i + NUM_COLUMNS] for i in range(0, len(modules), NUM_COLUMNS)]

    max_num_pages = ceil(len(pairs) / COLUMN_SIZE) if len(pairs) > 0 else 1
    modulo_page = page_n % max_num_pages

    if len(pairs) > COLUMN_SIZE:
        pairs = pairs[modulo_page * COLUMN_SIZE : COLUMN_SIZE * (modulo_page + 1)] + [
            (
                EqInlineKeyboardButton(
                    "⇜ ᴘʀᴇᴠ", # Keeping your navigation arrows
                    callback_data="{}_prev({})".format(
                        prefix,
                        modulo_page - 1 if modulo_page > 0 else max_num_pages - 1,
                    ),
                ),
                EqInlineKeyboardButton(
                    " ↻ ʙᴀᴄᴋ" if not close else "✖️ ᴄʟᴏsᴇ",
                    callback_data="settingsback_helper" if not close else "close",
                ),
                EqInlineKeyboardButton(
                    "ɴᴇxᴛ ⇝",
                    callback_data="{}_next({})".format(prefix, modulo_page + 1),
                ),
            )
        ]
    else:
        pairs.append(
            [
                EqInlineKeyboardButton(
                    " ↻ ʙᴀᴄᴋ" if not close else "✖️ ᴄʟᴏsᴇ",
                    callback_data="settingsback_helper" if not close else "close",
                ),
            ]
        )

    return pairs


@app.on_message(filters.command(HELP_COMMAND) & filters.private & ~BANNED_USERS)
@app.on_callback_query(filters.regex("settings_back_helper") & ~BANNED_USERS)
async def helper_private(
    client: app, update: Union[types.Message, types.CallbackQuery]
):
    is_callback = isinstance(update, types.CallbackQuery)
    
    text = (
        "<b>➲ ᴅᴀɴᴄᴇ ᴍᴀsᴛᴇʀ ʜᴇʟᴘ ᴍᴇɴᴜ</b>\n\n"
        "➤ ᴄʟɪᴄᴋ ᴏɴ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ\n"
        "   ᴇxᴘʟᴏʀᴇ ᴀʟʟ ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅs.\n\n"
        "<b>➜ ᴀʟʟ ᴍᴏᴅᴜʟᴇs ʟɪsᴛᴇᴅ ʜᴇʀᴇ:</b>"
    )

    if is_callback:
        try:
            await update.answer()
        except:
            pass
        keyboard = InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "help"))
        await update.edit_message_text(text, reply_markup=keyboard)
    else:
        if await is_commanddelete_on(update.chat.id):
            try:
                await update.delete()
            except:
                pass
        
        keyboard = InlineKeyboardMarkup(
            paginate_modules(0, HELPABLE, "help", close=True)
        )
        if START_IMG_URL:
            await update.reply_photo(
                photo=START_IMG_URL,
                caption=text,
                reply_markup=keyboard,
            )
        else:
            await update.reply_text(
                text=text,
                reply_markup=keyboard,
            )


@app.on_message(filters.command(HELP_COMMAND) & filters.group & ~BANNED_USERS)
@LanguageStart
async def help_com_group(client, message: Message, _):
    keyboard = private_help_panel(_)
    await message.reply_text(
        "➤ ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ʜᴇʟᴘ ɪɴ ᴘʀɪᴠᴀᴛᴇ.", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def help_parser(name, keyboard=None):
    if not keyboard:
        keyboard = InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "help"))
    return keyboard


@app.on_callback_query(filters.regex(r"help_(.*?)"))
async def help_button(client, query):
    mod_match = re.match(r"help_module\((.+?),(.+?)\)", query.data)
    prev_match = re.match(r"help_prev\((.+?)\)", query.data)
    next_match = re.match(r"help_next\((.+?)\)", query.data)
    back_match = re.match(r"help_back\((\d+)\)", query.data)
    
    top_text = (
        "<b>➲ ᴅᴀɴᴄᴇ ᴍᴀsᴛᴇʀ ʜᴇʟᴘ ᴍᴇɴᴜ</b>\n\n"
        "➤ ᴄʟɪᴄᴋ ᴏɴ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ\n"
        "   ᴇxᴘʟᴏʀᴇ ᴀʟʟ ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅs.\n\n"
        "<b>➜ ᴀʟʟ ᴍᴏᴅᴜʟᴇs ʟɪsᴛᴇᴅ ʜᴇʀᴇ:</b>"
    )
    
    if mod_match:
        module = mod_match.group(1)
        prev_page_num = int(mod_match.group(2))
        
        text = (
            f"<b>➲ ᴍᴏᴅᴜʟᴇ: {get_small_caps(HELPABLE[module].__MODULE__)}</b>\n"
            f"────────────────────\n"
            f"{HELPABLE[module].__HELP__}\n"
            f"────────────────────\n"
            f"<b>➘ ɴᴀᴠɪɢᴀᴛᴇ ᴜsɪɴɢ ʙᴜᴛᴛᴏɴs</b>"
        )

        key = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=" ↻ ʙᴀᴄᴋ", callback_data=f"help_back({prev_page_num})"
                    ),
                    InlineKeyboardButton(text="✖️ ᴄʟᴏsᴇ", callback_data="close"),
                ],
            ]
        )
        await query.message.edit(text=text, reply_markup=key)

    elif prev_match or next_match or back_match:
        curr_page = int((prev_match or next_match or back_match).group(1))
        await query.message.edit(
            text=top_text,
            reply_markup=InlineKeyboardMarkup(
                paginate_modules(curr_page, HELPABLE, "help")
            )
        )

    await client.answer_callback_query(query.id)
