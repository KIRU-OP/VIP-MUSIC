#
# Copyright (C) 2024 by THE-VIP-BOY-OP@Github, < https://github.com/THE-VIP-BOY-OP >.
#
# This file is part of < https://github.com/THE-VIP-BOY-OP/VIP-MUSIC > project,
# and is released under the MIT License.
# Please see < https://github.com/THE-VIP-BOY-OP/VIP-MUSIC/blob/master/LICENSE >
#
# All rights reserved.
#

# This aeval and sh module is taken from < https://github.com/TheHamkerCat/WilliamButcherBot >
# Credit goes to TheHamkerCat.
#
# Requires: pip install heroku3 speedtest-cli
#

import json
import os
import re
import shlex
import subprocess
import sys
import traceback
from inspect import getfullargspec
from io import StringIO
from time import time

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from VIPMUSIC import app
from VIPMUSIC.misc import SUDOERS
from VIPMUSIC.utils.cleanmode import protect_message

# =========================================================================
# SHARED CONFIG / STORAGE
# =========================================================================

SUDO_FILE = "sudoers.json"
SETTINGS_FILE = "bot_settings.json"
DEFAULT_SETTINGS = {"maintenance": False, "logger": False, "autoend": False}

HEROKU_API_KEY = os.environ.get("HEROKU_API_KEY")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")
UPSTREAM_REPO = os.environ.get(
    "UPSTREAM_REPO", "https://github.com/KIRU-OP/VIP-MUSIC"
)
UPSTREAM_BRANCH = os.environ.get("UPSTREAM_BRANCH", "master")


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f)


def _load_sudoers() -> set:
    return set(_load_json(SUDO_FILE, []))


def _save_sudoers(sudoers: set):
    _save_json(SUDO_FILE, list(sudoers))


def _load_settings() -> dict:
    data = _load_json(SETTINGS_FILE, DEFAULT_SETTINGS.copy())
    merged = DEFAULT_SETTINGS.copy()
    merged.update(data)
    return merged


def _save_settings(settings: dict):
    _save_json(SETTINGS_FILE, settings)


def is_maintenance_on() -> bool:
    return _load_settings().get("maintenance", False)


def is_logger_on() -> bool:
    return _load_settings().get("logger", False)


def is_autoend_on() -> bool:
    return _load_settings().get("autoend", False)


# Load persisted sudoers into the runtime SUDOERS set on import.
for uid in _load_sudoers():
    SUDOERS.add(uid)


# =========================================================================
# EVAL / SH  (original module, kept as-is with bug fixes)
# =========================================================================


async def aexec(code, client, message):
    exec(
        "async def __aexec(client, message): "
        + "".join(f"\n {a}" for a in code.split("\n"))
    )
    return await locals()["__aexec"](client, message)


async def edit_or_reply(msg: Message, **kwargs):
    func = msg.edit_text if msg.from_user.is_self else msg.reply
    spec = getfullargspec(func.__wrapped__).args
    await func(**{k: v for k, v in kwargs.items() if k in spec})
    await protect_message(msg.chat.id, msg.id)


@app.on_edited_message(
    filters.command(["ev", "eval"]) & SUDOERS & ~filters.forwarded & ~filters.via_bot
)
@app.on_message(
    filters.command(["ev", "eval"]) & SUDOERS & ~filters.forwarded & ~filters.via_bot
)
async def executor(client: app, message: Message):
    if len(message.command) < 2:
        return await edit_or_reply(message, text="<b>ᴡʜᴀᴛ ʏᴏᴜ ᴡᴀɴɴᴀ ᴇxᴇᴄᴜᴛᴇ ʙᴀʙʏ ?</b>")
    try:
        cmd = message.text.split(" ", maxsplit=1)[1]
    except IndexError:
        return await message.delete()
    t1 = time()
    old_stderr = sys.stderr
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    redirected_error = sys.stderr = StringIO()
    stdout, stderr, exc = None, None, None
    try:
        await aexec(cmd, client, message)
    except Exception:
        exc = traceback.format_exc()
    stdout = redirected_output.getvalue()
    stderr = redirected_error.getvalue()
    sys.stdout = old_stdout
    sys.stderr = old_stderr
    evaluation = "\n"
    if exc:
        evaluation += exc
    elif stderr:
        evaluation += stderr
    elif stdout:
        evaluation += stdout
    else:
        evaluation += "Success"
    final_output = f"<b>⥤ ʀᴇsᴜʟᴛ :</b>\n<pre language='python'>{evaluation}</pre>"
    if len(final_output) > 4096:
        filename = "output.txt"
        with open(filename, "w+", encoding="utf8") as out_file:
            out_file.write(str(evaluation))
        t2 = time()
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(text="⏳", callback_data=f"runtime {t2-t1} Seconds")]]
        )
        await message.reply_document(
            document=filename,
            caption=f"<b>⥤ ᴇᴠᴀʟ :</b>\n<code>{cmd[0:980]}</code>\n\n<b>⥤ ʀᴇsᴜʟᴛ :</b>\nAttached Document",
            quote=False,
            reply_markup=keyboard,
        )
        await message.delete()
        os.remove(filename)
    else:
        t2 = time()
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="⏳", callback_data=f"runtime {round(t2-t1, 3)} Seconds"
                    ),
                    InlineKeyboardButton(
                        text="🗑", callback_data=f"forceclose abc|{message.from_user.id}"
                    ),
                ]
            ]
        )
        await edit_or_reply(message, text=final_output, reply_markup=keyboard)


@app.on_callback_query(filters.regex(r"runtime"))
async def runtime_func_cq(_, cq):
    runtime = cq.data.split(None, 1)[1]
    await cq.answer(runtime, show_alert=True)


@app.on_callback_query(filters.regex("forceclose"))
async def forceclose_command(_, CallbackQuery):
    callback_data = CallbackQuery.data.strip()
    callback_request = callback_data.split(None, 1)[1]
    query, user_id = callback_request.split("|")
    if CallbackQuery.from_user.id != int(user_id):
        try:
            return await CallbackQuery.answer(
                "» ɪᴛ'ʟʟ ʙᴇ ʙᴇᴛᴛᴇʀ ɪғ ʏᴏᴜ sᴛᴀʏ ɪɴ ʏᴏᴜʀ ʟɪᴍɪᴛs ʙᴀʙʏ.", show_alert=True
            )
        except Exception:
            return
    await CallbackQuery.message.delete()
    try:
        await CallbackQuery.answer()
    except Exception:
        return


def _split_shell(text: str):
    parts = re.split(""" (?=(?:[^'"]|'[^']*'|"[^"]*")*$)""", text)
    return [p.replace('"', "").replace("'", "") for p in parts if p != ""]


def _run_shell(parts, timeout: int = 120):
    try:
        process = subprocess.Popen(parts, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception as err:
        return False, str(err)
    try:
        out, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        out, _ = process.communicate()
        return False, f"⏱ Command timed out after {timeout}s.\n{out.decode('utf-8', errors='ignore')}"
    return True, out.decode("utf-8", errors="ignore").rstrip("\n")


@app.on_edited_message(filters.command("sh") & SUDOERS & ~filters.forwarded & ~filters.via_bot)
@app.on_message(filters.command("sh") & SUDOERS & ~filters.forwarded & ~filters.via_bot)
async def shellrunner(_, message: Message):
    if len(message.command) < 2:
        return await edit_or_reply(message, text="<b>ᴇxᴀᴍᴩʟᴇ :</b>\n/sh git pull")

    text = message.text.split(None, 1)[1]
    output = ""

    if "\n" in text:
        for line in text.split("\n"):
            if not line.strip():
                continue
            ok, result = _run_shell(_split_shell(line))
            output += f"<b>{line}</b>\n"
            if not ok:
                output += f"ERROR: {result}\n"
                break
            output += f"{result}\n"
    else:
        ok, result = _run_shell(_split_shell(text))
        if not ok:
            return await edit_or_reply(message, text=f"<b>ERROR :</b>\n<pre>{result}</pre>")
        output = result

    if output.strip() in ("", "\n"):
        output = None

    if output:
        if len(output) > 4096:
            with open("output.txt", "w+", encoding="utf-8") as file:
                file.write(output)
            await app.send_document(
                message.chat.id, "output.txt", reply_to_message_id=message.id,
                caption="<code>Output</code>",
            )
            os.remove("output.txt")
        else:
            await edit_or_reply(message, text=f"<b>OUTPUT :</b>\n<pre>{output}</pre>")
    else:
        await edit_or_reply(message, text="<b>OUTPUT :</b>\n<code>None</code>")

    await message.stop_propagation()


# =========================================================================
# SUDO MANAGEMENT
# =========================================================================


async def _resolve_user_id(client, message: Message):
    if message.reply_to_message:
        u = message.reply_to_message.from_user
        return u.id, u.first_name
    if len(message.command) < 2:
        return None, None
    try:
        user = await client.get_users(message.command[1])
        return user.id, user.first_name
    except Exception:
        return None, None


@app.on_message(filters.command("addsudo") & SUDOERS)
async def add_sudo(client, message: Message):
    user_id, name = await _resolve_user_id(client, message)
    if not user_id:
        return await message.reply_text("<b>Usage:</b> reply to a user or /addsudo [username|user_id]")
    if user_id in SUDOERS:
        return await message.reply_text(f"<b>{name}</b> is already a sudo user.")
    SUDOERS.add(user_id)
    sudoers = _load_sudoers()
    sudoers.add(user_id)
    _save_sudoers(sudoers)
    await message.reply_text(f"✅ <b>{name}</b> added as a sudo user.")


@app.on_message(filters.command("delsudo") & SUDOERS)
async def del_sudo(client, message: Message):
    user_id, name = await _resolve_user_id(client, message)
    if not user_id:
        return await message.reply_text("<b>Usage:</b> reply to a user or /delsudo [username|user_id]")
    if user_id not in SUDOERS:
        return await message.reply_text(f"<b>{name}</b> is not a sudo user.")
    SUDOERS.discard(user_id)
    sudoers = _load_sudoers()
    sudoers.discard(user_id)
    _save_sudoers(sudoers)
    await message.reply_text(f"✅ <b>{name}</b> removed from sudo users.")


# =========================================================================
# HEROKU TOOLS
# =========================================================================


def _get_heroku_app():
    if not HEROKU_API_KEY or not HEROKU_APP_NAME:
        return None
    try:
        import heroku3

        conn = heroku3.from_key(HEROKU_API_KEY)
        return conn.apps()[HEROKU_APP_NAME]
    except ImportError:
        return "NO_LIB"
    except Exception:
        return None


@app.on_message(filters.command("usage") & SUDOERS)
async def dyno_usage(_, message: Message):
    heroku_app = _get_heroku_app()
    if heroku_app == "NO_LIB":
        return await message.reply_text("❌ Run: <code>pip install heroku3</code>")
    if not heroku_app:
        return await message.reply_text("❌ HEROKU_API_KEY/HEROKU_APP_NAME not set (or VPS deploy).")
    try:
        dynos = heroku_app.dynos()
        text = "<b>⥤ Dyno Status:</b>\n\n"
        text += "".join(f"• <b>{d.name}</b> — {d.state}\n" for d in dynos) or "No active dynos."
        await message.reply_text(text)
    except Exception as e:
        await message.reply_text(f"❌ Error:\n<pre>{e}</pre>")


@app.on_message(filters.command("get_var") & SUDOERS)
async def get_var(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("<b>Usage:</b> /get_var [VAR_NAME]")
    var_name = message.command[1]
    heroku_app = _get_heroku_app()
    if heroku_app and heroku_app != "NO_LIB":
        try:
            value = heroku_app.config().get(var_name)
        except Exception as e:
            return await message.reply_text(f"❌ Error:\n<pre>{e}</pre>")
    else:
        value = os.environ.get(var_name)
    if value is None:
        return await message.reply_text(f"❌ <code>{var_name}</code> not found.")
    await message.reply_text(f"<b>{var_name}</b> = <code>{value}</code>")


@app.on_message(filters.command("set_var") & SUDOERS)
async def set_var(_, message: Message):
    if len(message.command) < 3:
        return await message.reply_text("<b>Usage:</b> /set_var [VAR_NAME] [VALUE]")
    var_name = message.command[1]
    value = message.text.split(None, 2)[2]
    heroku_app = _get_heroku_app()
    if heroku_app and heroku_app != "NO_LIB":
        try:
            heroku_app.config()[var_name] = value
            return await message.reply_text(
                f"✅ <b>{var_name}</b> set on Heroku.\n⚠️ This triggers a dyno restart."
            )
        except Exception as e:
            return await message.reply_text(f"❌ Error:\n<pre>{e}</pre>")
    env_path = ".env"
    lines = open(env_path).readlines() if os.path.exists(env_path) else []
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{var_name}="):
            lines[i] = f"{var_name}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{var_name}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)
    os.environ[var_name] = value
    await message.reply_text(f"✅ <b>{var_name}</b> set in .env.\n⚠️ Restart to fully apply.")


@app.on_message(filters.command("del_var") & SUDOERS)
async def del_var(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("<b>Usage:</b> /del_var [VAR_NAME]")
    var_name = message.command[1]
    heroku_app = _get_heroku_app()
    if heroku_app and heroku_app != "NO_LIB":
        try:
            del heroku_app.config()[var_name]
            return await message.reply_text(f"✅ <b>{var_name}</b> deleted from Heroku.")
        except Exception as e:
            return await message.reply_text(f"❌ Error:\n<pre>{e}</pre>")
    env_path = ".env"
    if not os.path.exists(env_path):
        return await message.reply_text("❌ .env not found.")
    lines = open(env_path).readlines()
    new_lines = [l for l in lines if not l.strip().startswith(f"{var_name}=")]
    if len(new_lines) == len(lines):
        return await message.reply_text(f"❌ <code>{var_name}</code> not found.")
    with open(env_path, "w") as f:
        f.writelines(new_lines)
    os.environ.pop(var_name, None)
    await message.reply_text(f"✅ <b>{var_name}</b> deleted from .env.")


# =========================================================================
# RESTART / SPEEDTEST
# =========================================================================


@app.on_message(filters.command("restart") & SUDOERS)
async def restart_bot(_, message: Message):
    await message.reply_text("♻️ <b>Restarting bot...</b>")
    os.execl(sys.executable, sys.executable, "-m", "VIPMUSIC")


@app.on_message(filters.command("speedtest") & SUDOERS)
async def run_speedtest(_, message: Message):
    msg = await message.reply_text("⏳ <b>Running speedtest...</b>")
    try:
        import speedtest

        st = speedtest.Speedtest()
        st.get_best_server()
        download = st.download() / 1_000_000
        upload = st.upload() / 1_000_000
        ping = st.results.ping
        await msg.edit_text(
            "<b>⥤ Speedtest Result:</b>\n\n"
            f"📥 <b>Download:</b> {download:.2f} Mbps\n"
            f"📤 <b>Upload:</b> {upload:.2f} Mbps\n"
            f"📶 <b>Ping:</b> {ping:.2f} ms"
        )
    except ImportError:
        await msg.edit_text("❌ Run: <code>pip install speedtest-cli</code>")
    except Exception as e:
        await msg.edit_text(f"❌ Speedtest failed:\n<pre>{e}</pre>")


# =========================================================================
# MAINTENANCE / LOGGER / GET_LOG / AUTOEND
# =========================================================================


@app.on_message(filters.command("maintenance") & SUDOERS)
async def toggle_maintenance(_, message: Message):
    if len(message.command) < 2 or message.command[1].lower() not in ("enable", "disable"):
        return await message.reply_text("<b>Usage:</b> /maintenance [enable|disable]")
    mode = message.command[1].lower() == "enable"
    settings = _load_settings()
    settings["maintenance"] = mode
    _save_settings(settings)
    await message.reply_text(f"<b>Maintenance mode {'enabled ✅' if mode else 'disabled ❌'}</b>")
    # NOTE: your global message handler should check is_maintenance_on()
    # and block/reply to non-sudo users while True.


@app.on_message(filters.command("logger") & SUDOERS)
async def toggle_logger(_, message: Message):
    if len(message.command) < 2 or message.command[1].lower() not in ("enable", "disable"):
        return await message.reply_text("<b>Usage:</b> /logger [enable|disable]")
    mode = message.command[1].lower() == "enable"
    settings = _load_settings()
    settings["logger"] = mode
    _save_settings(settings)
    await message.reply_text(f"<b>Search query logging {'enabled ✅' if mode else 'disabled ❌'}</b>")
    # NOTE: your /play search handler should check is_logger_on() and, if
    # True, forward each searched query to LOG_GROUP_ID.


@app.on_message(filters.command("get_log") & SUDOERS)
async def get_log(_, message: Message):
    lines_to_get = 50
    if len(message.command) >= 2:
        try:
            lines_to_get = int(message.command[1])
        except ValueError:
            return await message.reply_text("<b>Usage:</b> /get_log [number_of_lines]")
    log_file = "log.txt"  # adjust to your actual log file path
    if not os.path.exists(log_file):
        return await message.reply_text(
            "❌ No local log file found. On Heroku use "
            "<code>heroku logs --tail -a YOUR_APP_NAME</code>."
        )
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        all_lines = f.readlines()
    tail = "".join(all_lines[-lines_to_get:])
    if not tail.strip():
        return await message.reply_text("Log file is empty.")
    if len(tail) > 4000:
        with open("recent_log.txt", "w", encoding="utf-8") as out:
            out.write(tail)
        await message.reply_document("recent_log.txt", caption=f"Last {lines_to_get} lines")
        os.remove("recent_log.txt")
    else:
        await message.reply_text(f"<pre>{tail}</pre>")


@app.on_message(filters.command("autoend") & SUDOERS)
async def toggle_autoend(_, message: Message):
    if len(message.command) < 2 or message.command[1].lower() not in ("enable", "disable"):
        return await message.reply_text("<b>Usage:</b> /autoend [enable|disable]")
    mode = message.command[1].lower() == "enable"
    settings = _load_settings()
    settings["autoend"] = mode
    _save_settings(settings)
    await message.reply_text(
        f"<b>Auto stream-end (after 3 min of no listeners) {'enabled ✅' if mode else 'disabled ❌'}</b>"
    )
    # NOTE: your py-tgcalls voice-chat handler needs a periodic check that,
    # if is_autoend_on() and a call has had 0 listeners for 3+ minutes,
    # calls your existing leave/stop-stream function for that chat.


# =========================================================================
# UPDATE / GITPULL  — auto-detects the correct branch, fixes the
# "Branch master not found in fetched refs" error permanently.
# =========================================================================


def _run(cmd: str, timeout: int = 60):
    try:
        result = subprocess.run(
            shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout
        )
        return result.returncode == 0, result.stdout.decode("utf-8", errors="ignore").strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out: {cmd}"
    except FileNotFoundError:
        return False, f"Command not found: {cmd.split()[0]}"
    except Exception as e:
        return False, str(e)


def _detect_remote_branch() -> str:
    ok, out = _run("git remote show origin")
    if ok:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("HEAD branch:"):
                branch = line.split(":", 1)[1].strip()
                if branch and branch != "(unknown)":
                    return branch
    return UPSTREAM_BRANCH


async def _git_update() -> str:
    log = []

    if not os.path.isdir(".git"):
        return (
            "❌ No `.git` folder found here. This usually means a container/Docker "
            "deploy where the repo was copied, not cloned — `git pull` can't work. "
            "Redeploy from source instead."
        )

    ok, out = _run("git remote get-url origin")
    if not ok:
        log.append("⚠️ No origin remote — adding it.")
        ok, out = _run(f"git remote add origin {UPSTREAM_REPO}")
        if not ok:
            return "❌ Failed to add origin:\n" + out
    elif out.strip() not in (UPSTREAM_REPO, UPSTREAM_REPO + ".git"):
        log.append(f"⚠️ origin pointed elsewhere ({out.strip()}) — fixing.")
        _run(f"git remote set-url origin {UPSTREAM_REPO}")

    if os.path.exists(".git/shallow"):
        log.append("ℹ️ Shallow clone detected — fetching full history.")
        ok, out = _run("git fetch --unshallow origin", timeout=120)
        if not ok:
            log.append("⚠️ Unshallow fetch failed, continuing:\n" + out)

    branch = _detect_remote_branch()
    if branch != UPSTREAM_BRANCH:
        log.append(f"⚠️ UPSTREAM_BRANCH=`{UPSTREAM_BRANCH}` but remote default is `{branch}` — using `{branch}`.")

    ok, out = _run(f"git fetch origin {branch}", timeout=120)
    if not ok:
        return "\n".join(log) + (
            "\n\n❌ git fetch failed:\n<pre>{}</pre>\n\n"
            "Likely causes: private repo needs credentials, no network access, "
            "or branch name mismatch.\n\nDebug manually:\n"
            "<code>git remote -v</code>\n<code>git fetch origin</code>\n<code>git branch -a</code>"
        ).format(out)

    ok, local_hash = _run("git rev-parse HEAD")
    ok2, remote_hash = _run(f"git rev-parse origin/{branch}")
    if ok and ok2 and local_hash.strip() == remote_hash.strip():
        return "\n".join(log) + "\n\n✅ Already up to date."

    ok, out = _run(f"git reset --hard origin/{branch}")
    if not ok:
        return "\n".join(log) + f"\n\n❌ git reset failed:\n<pre>{out}</pre>"

    log.append(f"✅ Updated to latest `{branch}`.")

    ok, out = _run("pip install --no-cache-dir -r requirements.txt", timeout=300)
    log.append("✅ requirements.txt reinstalled." if ok else "⚠️ requirements.txt install had issues.")

    return "\n".join(log)


@app.on_message(filters.command(["update", "gitpull"]) & SUDOERS)
async def update_command(_, message: Message):
    msg = await message.reply_text("🔄 <b>Checking for updates...</b>")
    result = await _git_update()
    await msg.edit_text(f"<b>⥤ Update Log:</b>\n\n{result}")
    if "Updated to latest" in result:
        await msg.edit_text(result + "\n\n♻️ Restarting...")
        os.execl(sys.executable, sys.executable, "-m", "VIPMUSIC")


# =========================================================================
# HELP TEXT
# =========================================================================

__MODULE__ = "Deᴠ"
__HELP__ = """
🔰<b><u>Aᴅᴅ Aɴᴅ Rᴇᴍᴏᴠᴇ Sᴜᴅᴏ Usᴇʀ's:</u></b>

★ <b>/addsudo [Usᴇʀɴᴀᴍᴇ ᴏʀ Rᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ]</b>
★ <b>/delsudo [Usᴇʀɴᴀᴍᴇ ᴏʀ Rᴇᴘʟʏ ᴛᴏ ᴀ ᴜsᴇʀ]</b>

🛃<b><u>Hᴇʀᴏᴋᴜ:</u></b>

★ <b>/usage</b> - Dʏɴᴏ Usᴀɢᴇ.
★ <b>/get_var</b> - Gᴇᴛ ᴀ ᴄᴏɴғɪɢ ᴠᴀʀ ғʀᴏᴍ Hᴇʀᴏᴋᴜ ᴏʀ .env
★ <b>/del_var</b> - Dᴇʟᴇᴛᴇ ᴀɴʏ ᴠᴀʀ ᴏɴ Hᴇʀᴏᴋᴜ ᴏʀ .ᴇɴᴠ.
★ <b>/set_var [Vᴀʀ Nᴀᴍᴇ] [Vᴀʟᴜᴇ]</b> - Sᴇᴛ ᴀ Vᴀʀ ᴏʀ Uᴘᴅᴀᴛᴇ ᴀ Vᴀʀ ᴏɴ ʜᴇʀᴏᴋᴜ ᴏʀ .ᴇɴᴠ. Sᴇᴘᴇʀᴀᴛᴇ Vᴀʀ ᴀɴᴅ ɪᴛs Vᴀʟᴜᴇ ᴡɪᴛʜ ᴀ sᴘᴀᴄᴇ.

🤖<b><u>Bᴏᴛ Cᴏᴍᴍᴀɴᴅs:</u></b>

★ <b>/restart</b> - Rᴇsᴛᴀʀᴛ ʏᴏᴜʀ Bᴏᴛ.
★ <b>/update , /gitpull</b> - Uᴘᴅᴀᴛᴇ Bᴏᴛ.
★ <b>/speedtest</b> - Cʜᴇᴄᴋ sᴇʀᴠᴇʀ sᴘᴇᴇᴅs
★ <b>/maintenance [ᴇɴᴀʙʟᴇ / ᴅɪsᴀʙʟᴇ]</b>
★ <b>/logger [ᴇɴᴀʙʟᴇ / ᴅɪsᴀʙʟᴇ]</b> - Bᴏᴛ ʟᴏɢs ᴛʜᴇ sᴇᴀʀᴄʜᴇᴅ ǫᴜᴇʀɪᴇs ɪɴ ʟᴏɢɢᴇʀ ɢʀᴏᴜᴘ.
★ <b>/get_log [Nᴜᴍʙᴇʀ ᴏғ Lɪɴᴇs]</b> - Gᴇᴛ ʟᴏɢ ᴏғ ʏᴏᴜʀ ʙᴏᴛ ғʀᴏᴍ ʜᴇʀᴏᴋᴜ ᴏʀ ᴠᴘs. Wᴏʀᴋs ғᴏʀ ʙᴏᴛʜ.
★ <b>/autoend [ᴇɴᴀʙʟᴇ|ᴅɪsᴀʙʟᴇ]</b> - Eɴᴀʙʟᴇ Aᴜᴛᴏ sᴛʀᴇᴀᴍ ᴇɴᴅ ᴀғᴛᴇʀ 𝟹 ᴍɪɴs ɪғ ɴᴏ ᴏɴᴇ ɪs ʟɪsᴛᴇɴɪɴɢ.

"""
