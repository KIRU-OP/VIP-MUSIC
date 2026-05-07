import re
import os
from os import getenv
from dotenv import load_dotenv
from pyrogram import filters

# Load environment variables from .env file
load_dotenv()

# ================================================================
# 🎵 CORE BOT CONFIGURATION (Get from my.telegram.org)
# ================================================================
API_ID = int(getenv("API_ID", "22421379")) 
API_HASH = getenv("API_HASH")
BOT_TOKEN = getenv("BOT_TOKEN")

# ================================================================
# 🗄️ DATABASE & STORAGE (MongoDB URI)
# ================================================================
MONGO_DB_URI = getenv("MONGO_DB_URI", None)

# ================================================================
# 🔌 EXTRA PLUGINS CONFIGURATION (External Modules)
# ================================================================
# Set to "True" to load extra plugins
EXTRA_PLUGINS = getenv("EXTRA_PLUGINS", "True")

# External plugins repository link
EXTRA_PLUGINS_REPO = getenv("EXTRA_PLUGINS_REPO", "https://github.com/lll-DEADLY-VENOM-lll/Extra-Plugin")

# Folder name in your extra plugins repo
EXTRA_PLUGINS_FOLDER = getenv("EXTRA_PLUGINS_FOLDER", "plugins")

# ================================================================
# ⚙️ BOT LIMITS & TIMEOUTS
# ================================================================
CLEANMODE_DELETE_MINS = int(getenv("CLEANMODE_MINS", "5")) 
DURATION_LIMIT_MIN = int(getenv("DURATION_LIMIT", "3000"))
SONG_DOWNLOAD_DURATION = int(getenv("SONG_DOWNLOAD_DURATION_LIMIT", "1000"))

# Video & Audio file size limits
TG_AUDIO_FILESIZE_LIMIT = int(getenv("TG_AUDIO_FILESIZE_LIMIT", "1073741824"))
TG_VIDEO_FILESIZE_LIMIT = int(getenv("TG_VIDEO_FILESIZE_LIMIT", "1073741824"))

# Download Sleep timings
YOUTUBE_DOWNLOAD_EDIT_SLEEP = int(getenv("YOUTUBE_EDIT_SLEEP", "3"))
TELEGRAM_DOWNLOAD_EDIT_SLEEP = int(getenv("TELEGRAM_EDIT_SLEEP", "5"))

# ================================================================
# 👥 OWNER & PERMISSIONS
# ================================================================
OWNER_ID = list(map(int, getenv("OWNER_ID", "6972508083").split()))
LOG_GROUP_ID = int(getenv("LOG_GROUP_ID", "-1002223516578"))

# ================================================================
# 🌐 SOCIALS & REPO LINKS
# ================================================================
SUPPORT_CHANNEL = getenv("SUPPORT_CHANNEL", "https://t.me/about_deadly_venom")
SUPPORT_GROUP = getenv("BOYS_STATUS_GROUP", "https://t.me/+wlfVE1P8C9QzOGI9")
SUPPORT_CHAT = getenv("SUPPORT_GROUP", "https://t.me/+wlfVE1P8C9QzOGI9")
GITHUB_REPO = getenv("GITHUB_REPO", "https://github.com/lll-DEADLY-VENOM-lll/VIPMUSIC")
PRIVACY_LINK = getenv("PRIVACY_LINK", "https://telegra.ph/Privacy-Policy-for-VIPMUSIC-08-30")

# ================================================================
# 🚀 UPSTREAM & DEPLOYMENT
# ================================================================
UPSTREAM_REPO = getenv("UPSTREAM_REPO", "https://github.com/lll-DEADLY-VENOM-lll/VIPMUSIC")
UPSTREAM_BRANCH = getenv("UPSTREAM_BRANCH", "master")
GIT_TOKEN = getenv("GIT_TOKEN", "")

HEROKU_API_KEY = getenv("HEROKU_API_KEY")
HEROKU_APP_NAME = getenv("HEROKU_APP_NAME")

# ================================================================
# 📻 STREAMING & PLAYLIST LIMITS
# ================================================================
VIDEO_STREAM_LIMIT = int(getenv("VIDEO_STREAM_LIMIT", "999"))
SERVER_PLAYLIST_LIMIT = int(getenv("SERVER_PLAYLIST_LIMIT", "500"))
PLAYLIST_FETCH_LIMIT = int(getenv("PLAYLIST_FETCH_LIMIT", "500"))

# Spotify Integration
SPOTIFY_CLIENT_ID = getenv("SPOTIFY_CLIENT_ID", "19609edb1b9f4ed7be0c8c1342039362")
SPOTIFY_CLIENT_SECRET = getenv("SPOTIFY_CLIENT_SECRET", "409e31d3ddd64af08cfcc3b0f064fcbe")

# ================================================================
# 🤖 BOT MODES & FEATURES
# ================================================================
AUTO_GCAST = getenv("AUTO_GCAST", "on")
AUTO_GCAST_MSG = getenv("AUTO_GCAST_MSG", "")
PRIVATE_BOT_MODE = getenv("PRIVATE_BOT_MODE", "False")
SET_CMDS = getenv("SET_CMDS", "False")

# Assistant Settings
AUTO_LEAVING_ASSISTANT = getenv("AUTO_LEAVING_ASSISTANT", "False")
AUTO_LEAVE_ASSISTANT_TIME = int(getenv("ASSISTANT_LEAVE_TIME", "1800"))

# Pyrogram Sessions
STRING1 = getenv("STRING_SESSION", None)
STRING2 = getenv("STRING_SESSION2", None)
STRING3 = getenv("STRING_SESSION3", None)
STRING4 = getenv("STRING_SESSION4", None)
STRING5 = getenv("STRING_SESSION5", None)

# ================================================================
# 🖼️ VISUALS (Images)
# ================================================================
BASE_IMG = "https://i.ibb.co/G3bVD6qb/x.jpg"

START_IMG_URL = getenv("START_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
PING_IMG_URL = getenv("PING_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
PLAYLIST_IMG_URL = getenv("PLAYLIST_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
GLOBAL_IMG_URL = getenv("GLOBAL_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
STATS_IMG_URL = getenv("STATS_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
TELEGRAM_AUDIO_URL = getenv("TELEGRAM_AUDIO_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
TELEGRAM_VIDEO_URL = getenv("TELEGRAM_VIDEO_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
STREAM_IMG_URL = getenv("STREAM_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
SOUNCLOUD_IMG_URL = getenv("SOUNCLOUD_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
YOUTUBE_IMG_URL = getenv("YOUTUBE_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
SPOTIFY_ARTIST_IMG_URL = getenv("SPOTIFY_ARTIST_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
SPOTIFY_ALBUM_IMG_URL = getenv("SPOTIFY_ALBUM_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")
SPOTIFY_PLAYLIST_IMG_URL = getenv("SPOTIFY_PLAYLIST_IMG_URL", "https://i.ibb.co/MyN2zmSC/x.jpg")

# ================================================================
# 🛠️ INTERNAL SYSTEM (Don't Touch)
# ================================================================
BANNED_USERS = filters.user()
YTDOWNLOADER = 1
LOG = 2
LOG_FILE_NAME = "VIPlogs.txt"
TEMP_DB_FOLDER = "tempdb"
adminlist = {}
lyrical = {}
chatstats = {}
userstats = {}
clean = {}
autoclean = []

def time_to_seconds(time):
    stringt = str(time)
    return sum(int(x) * 60**i for i, x in enumerate(reversed(stringt.split(":"))))

DURATION_LIMIT = int(time_to_seconds(f"{DURATION_LIMIT_MIN}:00"))
SONG_DOWNLOAD_DURATION_LIMIT = int(time_to_seconds(f"{SONG_DOWNLOAD_DURATION}:00"))

# --- Simple URL Check ---
for url_val in [SUPPORT_CHANNEL, SUPPORT_GROUP, UPSTREAM_REPO, GITHUB_REPO]:
    if url_val and not re.match(r"(?:http|https)://", url_val):
        print(f"[ERROR] - URL '{url_val}' is invalid!")

print("✅ Config Updated & Loaded!")
