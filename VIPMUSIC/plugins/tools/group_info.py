import asyncio

from pyrogram import enums, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from VIPMUSIC import app


@app.on_message(filters.command("id"))
async def get_id(client, message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else None
    lines = [f"<b>Your ID:</b> <code>{message.from_user.id}</code>", f"<b>Chat ID:</b> <code>{message.chat.id}</code>"]
    if target:
        lines.append(f"<b>Replied user ID:</b> <code>{target.id}</code>")
    elif len(message.command) > 1:
        try:
            user = await client.get_users(message.command[1])
            lines.append(f"<b>User ID:</b> <code>{user.id}</code>")
        except Exception:
            return await message.reply_text("User not found.")
    await message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="close")]]))


@app.on_message(filters.command("info"))
async def user_info(client, message: Message):
    try:
        user = message.reply_to_message.from_user if message.reply_to_message else await client.get_users(message.command[1] if len(message.command) > 1 else message.from_user.id)
    except Exception:
        return await message.reply_text("User not found.")
    text = (f"<b>User information</b>\n\n<b>ID:</b> <code>{user.id}</code>\n"
            f"<b>Name:</b> {user.first_name}\n<b>Username:</b> @{user.username if user.username else 'None'}\n"
            f"<b>Bot:</b> {'Yes' if user.is_bot else 'No'}")
    await message.reply_text(text)


@app.on_message(filters.command(["admins", "staff"]))
async def group_staff(client, message: Message):
    try:
        admins = []
        owner = None
        async for member in app.get_chat_members(message.chat.id, filter=enums.ChatMembersFilter.ADMINISTRATORS):
            if member.privileges and not member.privileges.is_anonymous and not member.user.is_bot:
                if member.status == ChatMemberStatus.OWNER:
                    owner = member.user
                else:
                    admins.append(member.user)
        lines = [f"<b>Group staff — {message.chat.title or 'chat'}</b>"]
        if owner:
            lines.append(f"\n<b>Owner:</b> {owner.mention}")
        lines.append("\n<b>Admins:</b>")
        lines.extend(f"• {user.mention}" for user in admins) if admins else lines.append("• Hidden or none")
        lines.append(f"\n<b>Total:</b> {len(admins) + bool(owner)}")
        await message.reply_text("\n".join(lines))
    except FloodWait as exc:
        await asyncio.sleep(exc.value)
    except RPCError as exc:
        await message.reply_text(f"Could not fetch staff: <code>{exc}</code>")


__MODULE__ = "Group tools"
__HELP__ = """**Group tools**

`/id`, `/info`, `/admins`, and `/staff`
"""
