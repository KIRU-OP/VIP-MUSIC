#
# Copyright (C) 2024 by THE-VIP-BOY-OP@Github, < https://github.com/THE-VIP-BOY-OP >.
#
# This file is part of < https://github.com/THE-VIP-BOY-OP/VIP-MUSIC > project,
# and is released under the MIT License.
#

from pyrogram import filters
from pyrogram.types import Message

import config
from strings import get_command
from VIPMUSIC import app
from VIPMUSIC.misc import SUDOERS
from VIPMUSIC.utils.database import add_off, add_on
from VIPMUSIC.utils.decorators.language import language

# कमांड लोड करना
VIDEOMODE_COMMAND = get_command("VIDEOMODE_COMMAND")

@app.on_message(filters.command(VIDEOMODE_COMMAND) & SUDOERS)
@language
async def videoloaymode(client, message: Message, _):
    usage = _["vidmode_1"]
    
    # चेक करना कि कमांड के साथ सही शब्द लिखा है या नहीं
    if len(message.command) != 2:
        return await message.reply_text(usage)
    
    state = message.text.split(None, 1)[1].strip().lower()
    
    if state == "download":
        await add_on(config.YTDOWNLOADER)
        await message.reply_text(_["vidmode_2"])
    elif state == "m3u8":
        await add_off(config.YTDOWNLOADER)
        await message.reply_text(_["vidmode_3"])
    else:
        # अगर यूजर ने 'download' या 'm3u8' के अलावा कुछ और लिखा
        await message.reply_text(usage)
