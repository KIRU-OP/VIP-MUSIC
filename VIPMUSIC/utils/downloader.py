import os
import re
import time
import asyncio
import logging
import functools
import yt_dlp

from VIPMUSIC.utils.cookie_handler import COOKIE_PATH

_logger = logging.getLogger("VIPMUSIC.utils.yt_dlp_download")

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MIN_VALID_SIZE = 10240  # 10 KB - anything smaller is treated as a failed/corrupt download
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2  # multiplied by attempt number

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Only warn about a missing/empty cookie file once, not on every single
# download call — otherwise logs fill up with the same warning repeatedly.
_cookie_warning_logged = False


def _cookie_opts() -> dict:
    global _cookie_warning_logged
    opts = {}
    try:
        if COOKIE_PATH and os.path.exists(COOKIE_PATH) and os.path.getsize(COOKIE_PATH) > 0:
            opts["cookiefile"] = str(COOKIE_PATH)
        elif not _cookie_warning_logged:
            _cookie_warning_logged = True
            _logger.warning(
                "Cookie file missing/empty at %s — downloading without auth. "
                "Export fresh cookies (yt-dlp --cookies-from-browser) and update COOKIE_PATH "
                "to reduce 'Sign in to confirm you're not a bot' errors.",
                COOKIE_PATH,
            )
    except Exception as e:
        _logger.error("Error checking cookie file: %s", e)
    return opts


def _bot_bypass_opts() -> dict:
    """
    Reduces how often YouTube's 'Sign in to confirm you're not a bot' check
    triggers. The android/ios player clients are hit far less often than the
    default web client. This does NOT replace cookies — with no valid cookie
    file YouTube can still reject the request — but it's a strong first line
    of defense and helps a lot even without cookies.
    """
    return {"extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}}}


def _video_id(link: str) -> str:
    return link.split("v=")[-1].split("&")[0] if "v=" in link else link


def _safe_filename(name: str) -> str:
    # search query ko safe filename me convert karta hai
    name = re.sub(r"[^\w\-_. ]", "_", name)
    return name.strip()[:80] or "audio"


def _base_ydl_opts(file_path: str, type: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "geo_bypass": True,
        "force_ipv4": True,
        "noplaylist": True,
        "outtmpl": file_path,
        "http_headers": {"User-Agent": _UA},
        "format": (
            "best[height<=?720][width<=?1280]/best"
            if type == "video"
            else "bestaudio[ext=webm]/bestaudio/best"
        ),
    }
    opts.update(_bot_bypass_opts())
    return opts


def _is_valid_file(file_path: str) -> bool:
    return os.path.exists(file_path) and os.path.getsize(file_path) > MIN_VALID_SIZE


def _is_bot_check_error(text: str) -> bool:
    if not text:
        return False
    t = str(text).lower()
    return "sign in to confirm" in t or "not a bot" in t


def _download_with_retries(ydl_opts: dict, target: str, file_path: str) -> str:
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([target])
            if _is_valid_file(file_path):
                return file_path
            last_err = "downloaded file missing or too small"
        except Exception as e:
            last_err = e
            msg = str(e)
            if "403" in msg or "Forbidden" in msg:
                _logger.warning(
                    "Attempt %d/%d: 403 Forbidden for %s — retrying.",
                    attempt, MAX_RETRIES, target,
                )
            elif _is_bot_check_error(msg):
                # This is a well-known, non-fatal YouTube bot-check block.
                # It's expected to happen sometimes even with the player-client
                # bypass in place, and this method usually loses the download
                # race to the primary API anyway — so keep it at INFO/WARNING
                # instead of flooding logs with ERROR-level noise on every hit.
                _logger.warning(
                    "Attempt %d/%d: bot-check block for %s (cookies %s). "
                    "See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp",
                    attempt, MAX_RETRIES, target,
                    "present" if ydl_opts.get("cookiefile") else "missing",
                )
                # Retrying immediately rarely helps a bot-check block — stop early.
                break
            else:
                _logger.error(
                    "Attempt %d/%d: download failed for %s: %s",
                    attempt, MAX_RETRIES, target, e,
                )
                # non-403/bot-check errors (bad link, no results, etc.) rarely
                # fix themselves - stop early.
                break

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    _logger.warning("Giving up on %s after retries. Last error: %s", target, last_err)
    return None


def _sync_download(link: str, type: str = "audio") -> str:
    video_id = _video_id(link)
    if not video_id or len(video_id) < 3:
        _logger.warning("Invalid/short video id extracted from link: %s", link)
        return None

    ext = "mp4" if type == "video" else "webm"
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")

    if _is_valid_file(file_path):
        return file_path

    ydl_opts = _base_ydl_opts(file_path, type)
    ydl_opts.update(_cookie_opts())

    return _download_with_retries(ydl_opts, link, file_path)


def _sync_download_by_name(query: str, type: str = "audio") -> str:
    """
    Song/video ka naam (query) leke YouTube pe search karta hai
    aur pehla result download karta hai.
    """
    if not query or len(query.strip()) < 2:
        _logger.warning("Empty/too-short search query received.")
        return None

    ext = "mp4" if type == "video" else "webm"
    safe_name = _safe_filename(query)
    file_path = os.path.join(DOWNLOAD_DIR, f"{safe_name}.{ext}")

    if _is_valid_file(file_path):
        return file_path

    ydl_opts = _base_ydl_opts(file_path, type)
    ydl_opts["default_search"] = "ytsearch1"  # sirf pehla result
    ydl_opts.update(_cookie_opts())

    return _download_with_retries(ydl_opts, f"ytsearch1:{query}", file_path)


async def yt_dlp_download(link: str, type: str = "audio") -> str:
    loop = asyncio.get_event_loop()
    func = functools.partial(_sync_download, link, type)
    return await loop.run_in_executor(None, func)


async def yt_dlp_download_by_name(query: str, type: str = "audio") -> str:
    loop = asyncio.get_event_loop()
    func = functools.partial(_sync_download_by_name, query, type)
    return await loop.run_in_executor(None, func)


async def download_audio_concurrent(link: str) -> str:
    return await yt_dlp_download(link, type="audio")


async def download_song_by_name(query: str) -> str:
    """Song naam se direct download (audio)."""
    return await yt_dlp_download_by_name(query, type="audio")
