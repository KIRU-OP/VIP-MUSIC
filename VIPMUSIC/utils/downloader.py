"""
Robust multi-source YouTube downloader — audio & video.

Har download 4 layers me try hota hai (jo bhi pehle kaam kar jaaye wahi use
hota hai, baaki skip):

    1. Primary Shruti API      (direct download, api_key based)
    2. Legacy Fallback API     (token based: /download -> token -> /stream)
    3. Worker Fallback API     (Cloudflare worker, direct download, key based)
    4. yt-dlp                  (local extraction, retries + bot-check aware)

Agar koi ek URL/key configure hi nahi hai to wo layer chup-chaap skip ho
jaati hai — kabhi crash nahi karti. Public function names purane jaise hi
hain (backward compatible) taaki existing imports na toote:

    yt_dlp_download(link, type)
    yt_dlp_download_by_name(query, type)
    download_audio_concurrent(link)
    download_song_by_name(query)

Naye, "comfort" entry points (link YA plain naam/query dono chalte hain):

    await download_audio("https://youtu.be/xyz")
    await download_audio("tum hi ho arijit singh")
    await download_video("...")
"""

import os
import re
import time
import shutil
import asyncio
import logging
import functools
import contextlib
from typing import Optional

import aiohttp
import aiofiles
import yt_dlp

from VIPMUSIC.utils.cookie_handler import COOKIE_PATH

_logger = logging.getLogger("VIPMUSIC.utils.yt_dlp_download")

# ============ GENERAL CONFIG ============
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MIN_VALID_SIZE = 10240  # 10 KB - isse chhota = corrupt/failed download
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2  # attempt number se multiply hota hai
MIN_FREE_DISK_MB = int(os.environ.get("MIN_FREE_DISK_MB", 500))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ============ API CONFIGURATION (Youtube.py jaisi hi, taaki dono consistent rahein) ============
SHRUTI_API_KEY = os.environ.get("SHRUTI_API_KEY", "ShrutiBotsPAVXJFsXdDeoJqDOe4NW")

PRIMARY_API_URL = os.environ.get("PRIMARY_API_URL", "https://api.shrutibots.site")
# /download?url={video_id}&type=audio|video&api_key={KEY} -> direct file

FALLBACK_API_URL = os.environ.get("FALLBACK_API_URL", "http://13.212.126.0:2020")
# /download?url={video_id}&type=... -> {"download_token": "..."}
# /stream/{video_id}?type=...       -> file, header X-Download-Token

WORKER_FALLBACK_API_URL = os.environ.get(
    "WORKER_FALLBACK_API_URL", "https://youtubenewapi.skybotsdeveloper.workers.dev"
)
WORKER_FALLBACK_API_KEY = os.environ.get("WORKER_FALLBACK_API_KEY", "itsmesid")
# /download?url={video_id}&type=...&key={KEY} -> direct file

_YT_URL_RE = re.compile(r"(?:youtube\.com|youtu\.be)", re.I)

# Only warn about a missing/empty cookie file once, not on every single
# download call — otherwise logs fill up with the same warning repeatedly.
_cookie_warning_logged = False

# ── Shared persistent HTTP session (reused across all 3 API tiers) ──
_yt_session: Optional[aiohttp.ClientSession] = None
_yt_session_lock = asyncio.Lock()


def _mask_key(key: Optional[str]) -> str:
    """Logs me full API key kabhi mat print karo — sirf pehchaan ke liye itna kaafi hai."""
    if not key:
        return "<empty>"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]} (len={len(key)})"


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
    triggers. android/ios player clients are hit far less often than the
    default web client. Does NOT replace cookies, but helps a lot even
    without them.
    """
    return {"extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}}}


def _video_id(link: str) -> str:
    """
    youtu.be / shorts / live / watch?v= — sab handle karta hai (Youtube.py
    ke _prepare_link jaisa hi), taaki koi bhi link format API tier ko sahi
    video id de sake.
    """
    link = link.split("&")[0]
    if "youtu.be/" in link:
        return link.rsplit("/", 1)[-1].split("?")[0]
    if "shorts/" in link or "youtube.com/live/" in link:
        return link.rsplit("/", 1)[-1].split("?")[0]
    if "v=" in link:
        return link.split("v=")[-1]
    return link


def _is_youtube_url(text: str) -> bool:
    text = (text or "").strip()
    return text.lower().startswith(("http://", "https://")) or bool(_YT_URL_RE.search(text))


def _safe_filename(name: str) -> str:
    # search query ko safe filename me convert karta hai
    name = re.sub(r"[^\w\-_. ]", "_", name)
    return name.strip()[:80] or "audio"


def _is_valid_file(file_path: str) -> bool:
    return os.path.exists(file_path) and os.path.getsize(file_path) > MIN_VALID_SIZE


def _is_bot_check_error(text: str) -> bool:
    if not text:
        return False
    t = str(text).lower()
    return "sign in to confirm" in t or "not a bot" in t


_AUDIO_EXTS = ("mp3", "webm", "m4a")
_VIDEO_EXTS = ("mp4", "webm")


def _find_cached(video_id: str, type: str) -> Optional[str]:
    """
    Alag-alag sources alag extensions me file save karte hain (APIs -> mp3/
    mp4, yt-dlp -> webm/mp4), isliye cache lookup sabhi possible extensions
    check karta hai — taaki kisi bhi source se pehle download hui file dobara
    network hit kiye bina turant mil jaaye.
    """
    for ext in (_AUDIO_EXTS if type == "audio" else _VIDEO_EXTS):
        p = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
        if _is_valid_file(p):
            return p
    return None


# ============ SHARED HTTP SESSION + DISK-SPACE GUARD ============
async def _get_session() -> aiohttp.ClientSession:
    global _yt_session
    if _yt_session and not _yt_session.closed:
        return _yt_session
    async with _yt_session_lock:
        if _yt_session and not _yt_session.closed:
            return _yt_session
        connector = aiohttp.TCPConnector(limit=32, ttl_dns_cache=300, enable_cleanup_closed=True)
        timeout = aiohttp.ClientTimeout(total=300, sock_connect=10, sock_read=60)
        _yt_session = aiohttp.ClientSession(
            connector=connector, timeout=timeout, headers={"User-Agent": _UA}
        )
        return _yt_session


async def close_session() -> None:
    """Bot shutdown par call karo taaki session cleanly band ho."""
    global _yt_session
    if _yt_session and not _yt_session.closed:
        await _yt_session.close()


def _sync_ensure_disk_space() -> None:
    """Disk kam ho to downloads/ me se sabse purani files delete karo jab tak jagah na ban jaaye."""
    try:
        free_mb = shutil.disk_usage(os.getcwd()).free / (1024 * 1024)
    except OSError:
        return
    if free_mb >= MIN_FREE_DISK_MB:
        return
    try:
        files = []
        for entry in os.scandir(DOWNLOAD_DIR):
            if entry.is_file():
                with contextlib.suppress(OSError):
                    st = entry.stat()
                    files.append((entry.path, st.st_mtime))
        files.sort(key=lambda x: x[1])  # oldest first (LRU)
        removed_any = False
        for path, _mtime in files:
            free_mb = shutil.disk_usage(os.getcwd()).free / (1024 * 1024)
            if free_mb >= MIN_FREE_DISK_MB:
                break
            with contextlib.suppress(OSError):
                os.remove(path)
                removed_any = True
        if removed_any:
            _logger.warning("⚠️ Low disk space — trimmed oldest files in downloads/.")
    except FileNotFoundError:
        pass


async def _ensure_disk_space() -> None:
    await asyncio.get_event_loop().run_in_executor(None, _sync_ensure_disk_space)


# ============ API 1: PRIMARY SHRUTI API (DIRECT DOWNLOAD) ============
async def _download_via_primary_api(video_id: str, type: str) -> Optional[str]:
    if not PRIMARY_API_URL:
        return None
    ext = "mp4" if type == "video" else "mp3"
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
    if _is_valid_file(file_path):
        return file_path
    try:
        await _ensure_disk_space()
        session = await _get_session()
        params = {"url": video_id, "type": type, "api_key": SHRUTI_API_KEY}
        timeout = aiohttp.ClientTimeout(total=180 if type == "video" else 120)
        async with session.get(f"{PRIMARY_API_URL}/download", params=params, timeout=timeout) as resp:
            if resp.status != 200:
                _logger.info("Primary API: HTTP %s for %s (%s)", resp.status, video_id, type)
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1 << 20):  # 1 MB
                    await f.write(chunk)
        if _is_valid_file(file_path):
            return file_path
        with contextlib.suppress(OSError):
            os.remove(file_path)
        return None
    except Exception as e:
        _logger.info("Primary API error for %s (%s): %s", video_id, type, e)
        return None


# ============ API 2: LEGACY/FALLBACK API (TOKEN BASED) ============
async def _download_via_fallback_api(video_id: str, type: str) -> Optional[str]:
    if not FALLBACK_API_URL:
        return None
    ext = "mp4" if type == "video" else "mp3"
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
    if _is_valid_file(file_path):
        return file_path
    try:
        await _ensure_disk_space()
        session = await _get_session()

        # Step 1: token lo
        async with session.get(
            f"{FALLBACK_API_URL}/download",
            params={"url": video_id, "type": type},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                _logger.info("Fallback API: token request HTTP %s for %s", resp.status, video_id)
                return None
            data = await resp.json()
            token = data.get("download_token")
            if not token:
                _logger.info("Fallback API: no download_token in response for %s", video_id)
                return None

        # Step 2: token se stream karo
        timeout = aiohttp.ClientTimeout(total=600 if type == "video" else 300)
        async with session.get(
            f"{FALLBACK_API_URL}/stream/{video_id}",
            params={"type": type},
            headers={"X-Download-Token": token},
            timeout=timeout,
        ) as file_resp:
            if file_resp.status != 200:
                _logger.info("Fallback API: stream HTTP %s for %s", file_resp.status, video_id)
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in file_resp.content.iter_chunked(1 << 20):
                    await f.write(chunk)

        if _is_valid_file(file_path):
            return file_path
        with contextlib.suppress(OSError):
            os.remove(file_path)
        return None
    except Exception as e:
        _logger.info("Fallback API error for %s (%s): %s", video_id, type, e)
        return None


# ============ API 3: WORKER FALLBACK API (CLOUDFLARE WORKER) ============
async def _download_via_worker_api(video_id: str, type: str) -> Optional[str]:
    if not WORKER_FALLBACK_API_URL:
        return None
    ext = "mp4" if type == "video" else "mp3"
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
    if _is_valid_file(file_path):
        return file_path
    try:
        await _ensure_disk_space()
        session = await _get_session()
        params = {"url": video_id, "type": type, "key": WORKER_FALLBACK_API_KEY}
        timeout = aiohttp.ClientTimeout(total=180 if type == "video" else 120)
        async with session.get(f"{WORKER_FALLBACK_API_URL}/download", params=params, timeout=timeout) as resp:
            if resp.status != 200:
                _logger.info("Worker API: HTTP %s for %s (%s)", resp.status, video_id, type)
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1 << 20):
                    await f.write(chunk)
        if _is_valid_file(file_path):
            return file_path
        with contextlib.suppress(OSError):
            os.remove(file_path)
        return None
    except Exception as e:
        _logger.info("Worker API error for %s (%s): %s", video_id, type, e)
        return None


# ============ LAYER 4: YT-DLP (LOCAL EXTRACTION, LAST RESORT) ============
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


def _download_with_retries(ydl_opts: dict, target: str, file_path: str) -> Optional[str]:
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
                # Well-known, non-fatal YouTube bot-check block. Expected to
                # happen sometimes even with the player-client bypass, and
                # this layer usually only runs after every API already
                # failed anyway — keep it at WARNING, not ERROR, and don't
                # burn retries on it since retrying rarely helps immediately.
                _logger.warning(
                    "Attempt %d/%d: bot-check block for %s (cookies %s). "
                    "See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp",
                    attempt, MAX_RETRIES, target,
                    "present" if ydl_opts.get("cookiefile") else "missing",
                )
                break
            else:
                _logger.error(
                    "Attempt %d/%d: download failed for %s: %s",
                    attempt, MAX_RETRIES, target, e,
                )
                # non-403/bot-check errors (bad link, no results, etc.) rarely
                # fix themselves — stop early.
                break

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    _logger.warning("Giving up on %s after retries. Last error: %s", target, last_err)
    return None


def _sync_download(link: str, type: str = "audio") -> Optional[str]:
    video_id = _video_id(link)
    if not video_id or len(video_id) < 3:
        _logger.warning("Invalid/short video id extracted from link: %s", link)
        return None

    ext = "mp4" if type == "video" else "webm"
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")

    if _is_valid_file(file_path):
        return file_path

    _sync_ensure_disk_space()
    ydl_opts = _base_ydl_opts(file_path, type)
    ydl_opts.update(_cookie_opts())

    return _download_with_retries(ydl_opts, link, file_path)


def _sync_download_by_name(query: str, type: str = "audio") -> Optional[str]:
    """Song/video ka naam (query) leke YouTube pe search karta hai aur pehla result download karta hai."""
    if not query or len(query.strip()) < 2:
        _logger.warning("Empty/too-short search query received.")
        return None

    ext = "mp4" if type == "video" else "webm"
    safe_name = _safe_filename(query)
    file_path = os.path.join(DOWNLOAD_DIR, f"{safe_name}.{ext}")

    if _is_valid_file(file_path):
        return file_path

    _sync_ensure_disk_space()
    ydl_opts = _base_ydl_opts(file_path, type)
    ydl_opts["default_search"] = "ytsearch1"  # sirf pehla result
    ydl_opts.update(_cookie_opts())

    return _download_with_retries(ydl_opts, f"ytsearch1:{query}", file_path)


def _sync_resolve_query_to_id(query: str) -> Optional[str]:
    """
    Plain naam/query ko ek video id me resolve karta hai (koi download nahi,
    sirf lookup) — taaki text query ke liye bhi Primary/Fallback/Worker API
    chain use ho sake (unhe kaam karne ke liye video id chahiye, naam nahi).
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
    }
    opts.update(_cookie_opts())
    opts.update(_bot_bypass_opts())
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            entries = (info or {}).get("entries") or []
            return entries[0].get("id") if entries else None
    except Exception as e:
        _logger.warning("Query resolution failed for %r: %s", query, e)
        return None


# ============ PUBLIC: LOW-LEVEL (yt-dlp only) — kept for backward compat ============
async def yt_dlp_download(link: str, type: str = "audio") -> Optional[str]:
    loop = asyncio.get_event_loop()
    func = functools.partial(_sync_download, link, type)
    return await loop.run_in_executor(None, func)


async def yt_dlp_download_by_name(query: str, type: str = "audio") -> Optional[str]:
    loop = asyncio.get_event_loop()
    func = functools.partial(_sync_download_by_name, query, type)
    return await loop.run_in_executor(None, func)


async def _resolve_query_to_id(query: str) -> Optional[str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_resolve_query_to_id, query)


# ============ PUBLIC: "COMFORT" ENTRY POINTS — sab APIs ek saath ============
async def _download(link_or_query: str, type: str) -> Optional[str]:
    """
    Ek hi function — link ho ya plain naam/query, dono chalte hain. Har
    video-id-based case me pura chain try hota hai:
        Primary API -> Fallback API -> Worker API -> yt-dlp
    """
    if _is_youtube_url(link_or_query):
        video_id = _video_id(link_or_query)
        if not video_id or len(video_id) < 3:
            _logger.warning("Invalid video id extracted from link: %s", link_or_query)
            return None

        cached = _find_cached(video_id, type)
        if cached:
            return cached

        for name, fn in (
            ("Primary API", _download_via_primary_api),
            ("Fallback API", _download_via_fallback_api),
            ("Worker API", _download_via_worker_api),
        ):
            _logger.info("%s: trying %s for %s", type, name, video_id)
            result = await fn(video_id, type)
            if result:
                _logger.info("%s: %s succeeded for %s", type, name, video_id)
                return result

        _logger.info("%s: all APIs failed for %s — falling back to yt-dlp", type, video_id)
        return await yt_dlp_download(link_or_query, type=type)

    # Plain text query: APIs need a video id, so resolve one first via a
    # cheap yt-dlp search (no 
