import asyncio
import contextlib
import json
import os
import re
import time
import aiofiles
import aiohttp
import shutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo  # stdlib, Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None

import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

from RishuMusic.utils.cookie_handler import COOKIE_PATH
from RishuMusic.utils.database import is_on_off
from RishuMusic.utils.errors import capture_internal_err
from RishuMusic.utils.formatters import time_to_seconds
from RishuMusic.utils.tuning import (
    YTDLP_TIMEOUT,
    YOUTUBE_META_MAX,
    YOUTUBE_META_TTL,
)
from RishuMusic import LOGGER

_module_logger = LOGGER(__name__)

_cache: Dict[str, Tuple[float, List[Dict]]] = {}
_cache_lock = asyncio.Lock()
_formats_cache: Dict[str, Tuple[float, List[Dict], str]] = {}
_formats_lock = asyncio.Lock()

# ============ API CONFIGURATION ============
SHRUTI_API_KEY = "ShrutiBotsPAVXJFsXdDeoJqDOe4NW"

# YouTube Data API v3 (official) — used for all search/metadata lookups.
# Replaces the old youtubesearchpython scraper, which broke silently whenever
# YouTube changed its page markup. Get a key from Google Cloud Console
# (enable "YouTube Data API v3") and set it as an env var.
#
# QUOTA NOTE: the free tier gives each key only 10,000 units/day (a search
# call costs ~100 units), so one key alone runs out fast under real traffic.
# To survive 24/7, set MULTIPLE keys as a comma-separated list in
# YOUTUBE_API_KEYS (e.g. "key1,key2,key3" — create each free in a separate
# Google Cloud project). The pool below automatically rotates to the next
# key the moment one hits quotaExceeded, so effective daily quota becomes
# 10,000 × number of keys. Only once EVERY key is exhausted does it fall
# back to the quota-free yt-dlp search (see _ytdlp_search_fallback below).
_raw_keys = os.environ.get("YOUTUBE_API_KEYS", "AIzaSyCDpYRd4S4xBboTyfVZ1rYsDtgnHmOlqIA").strip()
if _raw_keys:
    YOUTUBE_API_KEYS: List[str] = [k.strip() for k in _raw_keys.split(",") if k.strip()]
else:
    # Backward compatible: single-key env var (or the old hardcoded default).
    YOUTUBE_API_KEYS = [os.environ.get("YOUTUBE_API_KEY", "AIzaSyAuWd41xKkkd0HDq87dK9jHffW6lKzKWJs")]
YOUTUBE_V3_BASE_URL = "https://www.googleapis.com/youtube/v3"


def _mask_key(key: Optional[str]) -> str:
    """Never print the full API key to logs — only enough to tell keys apart.
    Defined up here (rather than further down, where it originally lived)
    because load_apis() below can run synchronously at import time — before
    later module-level definitions would otherwise exist — and now calls
    this for its startup log line."""
    if not key:
        return "<empty>"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]} (len={len(key)})"

# Per-key quota-exhaustion cooldown (epoch seconds; each key resets independently
# at midnight Pacific) + a round-robin pointer into YOUTUBE_API_KEYS.
_key_exhausted_until: Dict[str, float] = {}
_current_key_idx = 0
_key_rotation_lock = asyncio.Lock()

# API 1: Primary Shruti API (Direct Download)
PRIMARY_API_URL = "https://api.shrutibots.site"
# Endpoint: /download?url={video_id}&type=audio&api_key={KEY}
# Response: Direct file download

# API 2: Legacy/Fallback API (Token Based)
FALLBACK_API_URL = "http://13.212.126.0:2020"
# Endpoint 1: /download?url={video_id}&type=audio -> returns {"download_token": "xxx"}
# Endpoint 2: /stream/{video_id}?type=audio with header X-Download-Token

# API 3: Worker Fallback API (Direct Download, Cloudflare Worker)
WORKER_FALLBACK_API_URL = os.environ.get("WORKER_FALLBACK_API_URL", "https://youtubenewapi.skybotsdeveloper.workers.dev")
WORKER_FALLBACK_API_KEY = os.environ.get("WORKER_FALLBACK_API_KEY", "itsmesid")
# Endpoint: /download?url={video_id}&type=audio&key={KEY}
# Response: Direct file download

# API URLs loaded status
PRIMARY_API_LOADED = False
FALLBACK_API_LOADED = False
WORKER_FALLBACK_API_LOADED = False

# ============ DOWNLOAD CACHE MANAGEMENT (prevents "No space left on device") ============
# Root cause of the disk-full crashes: every downloaded file in downloads/ was
# kept forever (used as a cache) with nothing ever deleting old entries.
# This section adds automatic LRU + age based eviction so the disk never fills up.
DOWNLOAD_CACHE_DIR = "downloads"
MAX_CACHE_SIZE_MB = int(os.environ.get("MAX_CACHE_SIZE_MB", 2048))   # trim cache above this size
MAX_CACHE_AGE_HOURS = int(os.environ.get("MAX_CACHE_AGE_HOURS", 6))  # delete anything older than this
MIN_FREE_DISK_MB = int(os.environ.get("MIN_FREE_DISK_MB", 500))      # panic threshold -> aggressive cleanup
CACHE_CLEANUP_INTERVAL_SEC = int(os.environ.get("CACHE_CLEANUP_INTERVAL_SEC", 600))  # background sweep every 10 min

_cache_cleanup_lock = asyncio.Lock()


def _dir_size_and_files(path: str) -> Tuple[int, List[Tuple[str, float, int]]]:
    """Returns (total_size_bytes, [(filepath, mtime, size_bytes), ...]) for a directory."""
    total = 0
    files: List[Tuple[str, float, int]] = []
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                try:
                    st = entry.stat()
                    files.append((entry.path, st.st_mtime, st.st_size))
                    total += st.st_size
                except OSError:
                    continue
    except FileNotFoundError:
        pass
    return total, files


def _cleanup_downloads_sync(aggressive: bool = False) -> None:
    """
    Blocking cleanup of the downloads/ cache. Always run via cleanup_downloads()
    (thread executor) so it never blocks the event loop.
      1. Deletes anything older than MAX_CACHE_AGE_HOURS.
      2. If still over MAX_CACHE_SIZE_MB (or `aggressive`, e.g. disk almost full),
         deletes oldest files first (LRU) until back under the target size.
    """
    os.makedirs(DOWNLOAD_CACHE_DIR, exist_ok=True)
    now = time.time()
    max_age_sec = MAX_CACHE_AGE_HOURS * 3600
    total, files = _dir_size_and_files(DOWNLOAD_CACHE_DIR)

    kept: List[Tuple[str, float, int]] = []
    for path, mtime, size in files:
        if now - mtime > max_age_sec:
            with contextlib.suppress(OSError):
                os.remove(path)
                total -= size
        else:
            kept.append((path, mtime, size))

    cap_bytes = MAX_CACHE_SIZE_MB * 1024 * 1024
    target_bytes = cap_bytes // 2 if aggressive else cap_bytes
    if total > target_bytes:
        kept.sort(key=lambda x: x[1])  # oldest (LRU) first
        for path, mtime, size in kept:
            if total <= target_bytes:
                break
            with contextlib.suppress(OSError):
                os.remove(path)
                total -= size

    if aggressive:
        _module_logger.warning(
            f"⚠️ Low disk space — aggressively trimmed downloads/ cache (now ~{total // (1024 * 1024)} MB)"
        )


async def cleanup_downloads(aggressive: bool = False) -> None:
    """Async-safe wrapper: runs the blocking cleanup in a thread executor."""
    async with _cache_cleanup_lock:
        await asyncio.get_event_loop().run_in_executor(None, _cleanup_downloads_sync, aggressive)


_last_diag_log_time = 0.0
_DIAG_LOG_COOLDOWN_SEC = 1800  # only log the full disk breakdown once per 30 min


async def _ensure_disk_space() -> None:
    """
    Call this immediately before writing a new file to disk. If free space is
    below MIN_FREE_DISK_MB, forces an aggressive cache trim first (both our
    downloads/ cache and yt-dlp's own cache) so the write doesn't crash with
    [Errno 28] No space left on device.

    Also logs a full disk breakdown (total/used/free + biggest top-level dirs
    on this filesystem), throttled to once per _DIAG_LOG_COOLDOWN_SEC, so the
    cause is visible directly in the bot logs without needing separate SSH access.
    """
    global _last_diag_log_time
    try:
        usage = shutil.disk_usage(os.getcwd())
        free_mb = usage.free / (1024 * 1024)
        total_mb = usage.total / (1024 * 1024)
        used_mb = usage.used / (1024 * 1024)
    except OSError:
        return
    if free_mb < MIN_FREE_DISK_MB:
        cache_mb_before, _ = _dir_size_and_files(DOWNLOAD_CACHE_DIR)
        cache_mb_before = cache_mb_before / (1024 * 1024)
        await cleanup_downloads(aggressive=True)
        await _cleanup_ytdlp_cache()

        now = time.time()
        if now - _last_diag_log_time > _DIAG_LOG_COOLDOWN_SEC:
            _last_diag_log_time = now
            _module_logger.warning(
                f"⚠️ DISK DIAGNOSTIC — total={total_mb:.0f}MB used={used_mb:.0f}MB free={free_mb:.0f}MB | "
                f"downloads/ cache was {cache_mb_before:.0f}MB before trim | "
                f"non-download usage on this disk ≈ {used_mb - cache_mb_before:.0f}MB "
                f"(this is what's actually filling the disk — not the bot's download cache)"
            )
            await _log_top_disk_consumers()


async def _log_top_disk_consumers() -> None:
    """
    Logs the top few largest top-level directories under the bot's working
    directory tree, so the real disk hog shows up directly in bot logs
    (useful when SSH access to run `du -sh` manually isn't convenient).
    Runs in a thread executor so it never blocks the event loop; capped to
    avoid slow scans on huge filesystems.
    """
    def _scan():
        base = os.getcwd()
        results = []
        try:
            with os.scandir(base) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            size = 0
                            count = 0
                            for root, dirs, files in os.walk(entry.path, followlinks=False):
                                for f in files:
                                    count += 1
                                    if count > 20000:  # safety cap
                                        raise StopIteration
                                    try:
                                        size += os.path.getsize(os.path.join(root, f))
                                    except OSError:
                                        continue
                            results.append((entry.name, size))
                        elif entry.is_file(follow_symlinks=False):
                            try:
                                results.append((entry.name, entry.stat().st_size))
                            except OSError:
                                continue
                    except (StopIteration, OSError):
                        continue
        except OSError:
            pass
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:8]

    try:
        top = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _scan), timeout=20
        )
        if top:
            breakdown = ", ".join(f"{name}={size / (1024 * 1024):.0f}MB" for name, size in top)
            _module_logger.warning(f"⚠️ TOP DISK CONSUMERS (bot working dir): {breakdown}")
    except Exception:
        pass


async def _cache_cleanup_loop():
    """Background task: periodically trims downloads/ and yt-dlp's own cache so disk never fills up."""
    while True:
        try:
            await cleanup_downloads(aggressive=False)
            await _cleanup_ytdlp_cache()
        except Exception as e:
            _module_logger.warning(f"⚠️ Cache cleanup loop error: {e}")
        await asyncio.sleep(CACHE_CLEANUP_INTERVAL_SEC)


async def _cleanup_ytdlp_cache() -> None:
    """
    yt-dlp keeps its own cache (nsig/player responses etc.) outside downloads/,
    usually under ~/.cache/yt-dlp. This is a separate disk hog from the download
    cache and won't be touched by cleanup_downloads(), so it's purged here too.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--rm-cache-dir",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.communicate(), timeout=15)
    except Exception:
        pass

# ============ RATE LIMITING (async â€” does NOT block the event loop) ============
_request_timestamps = []
_RATE_LIMIT_WINDOW = 60
_MAX_REQUESTS_PER_WINDOW = 10
_rate_limit_lock = asyncio.Lock()

async def _check_rate_limit_async():
    """Non-blocking async rate-limit guard (replaces the old blocking time.sleep)."""
    global _request_timestamps
    async with _rate_limit_lock:
        now = time.time()
        _request_timestamps = [ts for ts in _request_timestamps if now - ts < _RATE_LIMIT_WINDOW]
        if len(_request_timestamps) >= _MAX_REQUESTS_PER_WINDOW:
            sleep_time = _RATE_LIMIT_WINDOW - (now - _request_timestamps[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            _request_timestamps = []
        _request_timestamps.append(time.time())


# â”€â”€ Shared persistent HTTP session for all API calls â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_yt_session: aiohttp.ClientSession = None
_yt_session_lock = asyncio.Lock()

async def _get_yt_session() -> aiohttp.ClientSession:
    global _yt_session
    if _yt_session and not _yt_session.closed:
        return _yt_session
    async with _yt_session_lock:
        if _yt_session and not _yt_session.closed:
            return _yt_session
        connector = aiohttp.TCPConnector(limit=32, ttl_dns_cache=300, enable_cleanup_closed=True)
        timeout = aiohttp.ClientTimeout(total=300, sock_connect=10, sock_read=60)
        _yt_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return _yt_session


async def load_apis():
    """Load and verify APIs - only checks non-empty URLs."""
    global PRIMARY_API_LOADED, FALLBACK_API_LOADED, WORKER_FALLBACK_API_LOADED
    logger = LOGGER("VISHALMUSIC.platforms.Youtube.py")

    # Log key-pool size on startup so "search stopped working" is easy to
    # diagnose from logs alone (e.g. only 1 key configured -> quota runs out
    # fast; env var not read at all -> falls back to the hardcoded default).
    logger.info(
        f"[INFO] YouTube Data API v3 key pool: {len(YOUTUBE_API_KEYS)} key(s) configured "
        f"({', '.join(_mask_key(k) for k in YOUTUBE_API_KEYS)})"
    )

    if PRIMARY_API_URL:
        try:
            session = await _get_yt_session()
            async with session.get(f"{PRIMARY_API_URL}/", timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status == 200:
                    PRIMARY_API_LOADED = True
                    logger.info(f"[OK] PRIMARY API loaded: {PRIMARY_API_URL}")
                else:
                    logger.warning(f"[WARN] Primary API status {response.status}")
        except Exception as e:
            logger.warning(f"[WARN] Primary API unreachable: {e}")

    if FALLBACK_API_URL:  # only check when a URL is actually configured
        try:
            session = await _get_yt_session()
            async with session.get(f"{FALLBACK_API_URL}/", timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status == 200:
                    FALLBACK_API_LOADED = True
                    logger.info(f"[OK] FALLBACK API loaded: {FALLBACK_API_URL}")
        except Exception as e:
            logger.warning(f"[WARN] Fallback API unreachable: {e}")

    if WORKER_FALLBACK_API_URL:
        try:
            session = await _get_yt_session()
            async with session.get(f"{WORKER_FALLBACK_API_URL}/", timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status == 200:
                    WORKER_FALLBACK_API_LOADED = True
                    logger.info(f"[OK] WORKER FALLBACK API loaded: {WORKER_FALLBACK_API_URL}")
                else:
                    logger.warning(f"[WARN] Worker Fallback API status {response.status}")
        except Exception as e:
            logger.warning(f"[WARN] Worker Fallback API unreachable: {e}")

    return PRIMARY_API_LOADED, FALLBACK_API_LOADED, WORKER_FALLBACK_API_LOADED

# Initialize APIs + start background cache cleanup on startup
try:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.create_task(load_apis())
        asyncio.create_task(_cache_cleanup_loop())
    else:
        loop.run_until_complete(load_apis())
        loop.create_task(_cache_cleanup_loop())
except RuntimeError:
    pass

def _cookiefile_path() -> Optional[str]:
    path = str(COOKIE_PATH)
    try:
        if path and os.path.exists(path) and os.path.getsize(path) > 0:
            return path
    except Exception:
        pass
    return None

def _cookies_args() -> List[str]:
    p = _cookiefile_path()
    return ["--cookies", p] if p else []

def _bot_bypass_args() -> List[str]:
    """
    Extra yt-dlp args that reduce the frequency of YouTube's
    'Sign in to confirm you're not a bot' block. This does NOT replace
    cookies -- if there is no valid cookie file, YouTube can still reject
    the request -- but the android/ios player clients are generally hit
    less hard than the default web client, so this is a useful first line
    of defense and a good fallback when cookies alone aren't enough.
    """
    return ["--extractor-args", "youtube:player_client=android,ios,web"]

def _yt_dlp_cli_args() -> List[str]:
    """Combined cookie + bot-bypass args shared by every yt-dlp subprocess call."""
    return _cookies_args() + _bot_bypass_args()

def _is_bot_check_error(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return "sign in to confirm" in t or "not a bot" in t

async def _exec_proc(*args: str) -> Tuple[bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=YTDLP_TIMEOUT)
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            proc.kill()
        return b"", b"timeout"

# Legacy sync alias removed â€” use _check_rate_limit_async() everywhere

# ============ API 1: PRIMARY SHRUTI API (DIRECT DOWNLOAD) ============
async def download_song_primary_api(link: str) -> str:
    """Primary Shruti API - Direct download with API key (shared session, 1 MB chunks)."""
    if not PRIMARY_API_URL:
        return None
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    if not video_id or len(video_id) < 3:
        return None

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        await _ensure_disk_space()
        session = await _get_yt_session()
        params = {"url": video_id, "type": "audio", "api_key": SHRUTI_API_KEY}
        async with session.get(
            f"{PRIMARY_API_URL}/download",
            params=params,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as response:
            if response.status != 200:
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in response.content.iter_chunked(1 << 20):  # 1 MB
                    await f.write(chunk)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path
        return None
    except Exception:
        return None


async def download_video_primary_api(link: str) -> str:
    """Primary Shruti API - Video download with API key (shared session, 1 MB chunks)."""
    if not PRIMARY_API_URL:
        return None
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    if not video_id or len(video_id) < 3:
        return None

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        await _ensure_disk_space()
        session = await _get_yt_session()
        params = {"url": video_id, "type": "video", "api_key": SHRUTI_API_KEY}
        async with session.get(
            f"{PRIMARY_API_URL}/download",
            params=params,
            timeout=aiohttp.ClientTimeout(total=180),
        ) as response:
            if response.status != 200:
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in response.content.iter_chunked(1 << 20):  # 1 MB
                    await f.write(chunk)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path
        return None
    except Exception:
        return None


# ============ API 2: LEGACY/FALLBACK API (TOKEN BASED) ============
async def download_song_fallback_api(link: str) -> str:
    """Legacy/Fallback API - Token based download (shared session, 1 MB chunks)."""
    if not FALLBACK_API_URL:
        return None
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    if not video_id or len(video_id) < 3:
        return None

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        await _ensure_disk_space()
        session = await _get_yt_session()
        # Step 1: get token
        async with session.get(
            f"{FALLBACK_API_URL}/download",
            params={"url": video_id, "type": "audio"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                return None
            data = await response.json()
            download_token = data.get("download_token")
            if not download_token:
                return None

        # Step 2: stream file
        async with session.get(
            f"{FALLBACK_API_URL}/stream/{video_id}?type=audio",
            headers={"X-Download-Token": download_token},
            timeout=aiohttp.ClientTimeout(total=300),
        ) as file_response:
            if file_response.status != 200:
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in file_response.content.iter_chunked(1 << 20):
                    await f.write(chunk)

        return file_path if os.path.exists(file_path) and os.path.getsize(file_path) > 0 else None
    except Exception:
        return None


async def download_video_fallback_api(link: str) -> str:
    """Legacy/Fallback API - Video download with token (shared session, 1 MB chunks)."""
    if not FALLBACK_API_URL:
        return None
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    if not video_id or len(video_id) < 3:
        return None

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        await _ensure_disk_space()
        session = await _get_yt_session()
        # Step 1: get token
        async with session.get(
            f"{FALLBACK_API_URL}/download",
            params={"url": video_id, "type": "video"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                return None
            data = await response.json()
            download_token = data.get("download_token")
            if not download_token:
                return None

        # Step 2: stream file
        async with session.get(
            f"{FALLBACK_API_URL}/stream/{video_id}?type=video",
            headers={"X-Download-Token": download_token},
            timeout=aiohttp.ClientTimeout(total=600),
        ) as file_response:
            if file_response.status != 200:
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in file_response.content.iter_chunked(1 << 20):
                    await f.write(chunk)

        return file_path if os.path.exists(file_path) and os.path.getsize(file_path) > 0 else None
    except Exception:
        return None


# ============ API 3: WORKER FALLBACK API (DIRECT DOWNLOAD, CLOUDFLARE WORKER) ============
async def download_song_worker_api(link: str) -> str:
    """Worker Fallback API - Direct download with API key (shared session, 1 MB chunks)."""
    if not WORKER_FALLBACK_API_URL:
        return None
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    if not video_id or len(video_id) < 3:
        return None

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        await _ensure_disk_space()
        session = await _get_yt_session()
        params = {"url": video_id, "type": "audio", "key": WORKER_FALLBACK_API_KEY}
        async with session.get(
            f"{WORKER_FALLBACK_API_URL}/download",
            params=params,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as response:
            if response.status != 200:
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in response.content.iter_chunked(1 << 20):  # 1 MB
                    await f.write(chunk)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path
        return None
    except Exception:
        return None


async def download_video_worker_api(link: str) -> str:
    """Worker Fallback API - Video download with API key (shared session, 1 MB chunks)."""
    if not WORKER_FALLBACK_API_URL:
        return None
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    if not video_id or len(video_id) < 3:
        return None

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        await _ensure_disk_space()
        session = await _get_yt_session()
        params = {"url": video_id, "type": "video", "key": WORKER_FALLBACK_API_KEY}
        async with session.get(
            f"{WORKER_FALLBACK_API_URL}/download",
            params=params,
            timeout=aiohttp.ClientTimeout(total=180),
        ) as response:
            if response.status != 200:
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in response.content.iter_chunked(1 << 20):  # 1 MB
                    await f.write(chunk)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path
        return None
    except Exception:
        return None


# ============ YT-DLP FALLBACK ============
async def download_video_ytdlp(link: str) -> str:
    """Download video using yt-dlp directly"""
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link

    if not video_id or len(video_id) < 3:
        return None

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 10240:
        return file_path

    await _check_rate_limit_async()
    await _ensure_disk_space()

    try:
        ytdlp_opts = [
            "yt-dlp",
            *(_yt_dlp_cli_args()),
            "--no-warnings",
            "--geo-bypass",
            "--force-ipv4",
            "-f",
            "best[height<=?720][width<=?1280]/best",
            "-o",
            file_path,
            link
        ]
        
        stdout, stderr = await _exec_proc(*ytdlp_opts)
        
        if os.path.exists(file_path) and os.path.getsize(file_path) > 10240:
            return file_path
        else:
            alternative_formats = ["best[ext=mp4]", "best", "worst[ext=mp4]", "worst"]
            
            for fmt in alternative_formats:
                try:
                    ytdlp_opts = [
                        "yt-dlp",
                        *(_yt_dlp_cli_args()),
                        "--no-warnings",
                        "--geo-bypass",
                        "--force-ipv4",
                        "-f",
                        fmt,
                        "-o",
                        file_path,
                        link
                    ]
                    
                    stdout, stderr = await _exec_proc(*ytdlp_opts)
                    
                    if os.path.exists(file_path) and os.path.getsize(file_path) > 10240:
                        return file_path
                    
                    await asyncio.sleep(1)
                except Exception:
                    continue
            
            return None

    except Exception as e:
        return None


async def download_audio_ytdlp(link: str) -> str:
    """Download audio using yt-dlp directly"""
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link

    if not video_id or len(video_id) < 3:
        return None

    DOWNLOAD_DIR = "downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.webm")

    # BUG FIX: this cache check had no size guard (unlike every other cache
    # check in the file), so a corrupt/empty leftover file from a previous
    # failed download would be returned as a "successful" result forever.
    if os.path.exists(file_path) and os.path.getsize(file_path) > 10240:
        return file_path

    await _check_rate_limit_async()
    await _ensure_disk_space()

    try:
        ytdlp_opts = [
            "yt-dlp",
            *(_yt_dlp_cli_args()),
            "--no-warnings",
            "--geo-bypass",
            "--force-ipv4",
            "-f",
            "bestaudio[ext=webm]/bestaudio",
            "--extract-audio",
            "--audio-format", "webm",
            "-o",
            file_path,
            link
        ]
        
        stdout, stderr = await _exec_proc(*ytdlp_opts)
        
        if os.path.exists(file_path) and os.path.getsize(file_path) > 10240:
            return file_path
        else:
            alternative_formats = ["bestaudio[ext=m4a]/bestaudio", "bestaudio/best", "worstaudio"]
            
            for fmt in alternative_formats:
                try:
                    alt_file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.webm")
                    ytdlp_opts = [
                        "yt-dlp",
                        *(_yt_dlp_cli_args()),
                        "--no-warnings",
                        "--geo-bypass",
                        "--force-ipv4",
                        "-f",
                        fmt,
                        "--extract-audio",
                        "--audio-format", "webm",
                        "-o",
                        alt_file_path,
                        link
                    ]
                    
                    stdout, stderr = await _exec_proc(*ytdlp_opts)
                    
                    if os.path.exists(alt_file_path) and os.path.getsize(alt_file_path) > 10240:
                        return alt_file_path
                    
                    await asyncio.sleep(1)
                except Exception:
                    continue
            
            return None

    except Exception as e:
        return None


# ============ MAIN DOWNLOAD FUNCTIONS (API1 -> API2 -> YTDLP) ============
async def download_audio(link: str) -> str:
    """
    Main audio download - Primary API -> Fallback API -> Worker Fallback API -> yt-dlp
    """
    # 1. TRY PRIMARY API FIRST
    _module_logger.info("🎵 Audio Download - Trying Primary API (Direct)...")
    result = await download_song_primary_api(link)
    if result:
        _module_logger.info("✅ Audio: Primary API Success")
        return result
    
    # 2. TRY FALLBACK API (TOKEN BASED)
    _module_logger.info("🔄 Audio - Primary failed, trying Fallback API (Token)...")
    result = await download_song_fallback_api(link)
    if result:
        _module_logger.info("✅ Audio: Fallback API Success")
        return result

    # 3. TRY WORKER FALLBACK API (DIRECT DOWNLOAD)
    _module_logger.info("🔄 Audio - Fallback API failed, trying Worker Fallback API...")
    result = await download_song_worker_api(link)
    if result:
        _module_logger.info("✅ Audio: Worker Fallback API Success")
        return result

    # 4. TRY YT-DLP AS LAST RESORT
    _module_logger.info("🔄 Audio - All APIs failed, trying yt-dlp fallback...")
    result = await download_audio_ytdlp(link)
    if result:
        _module_logger.info("✅ Audio: yt-dlp Success")
        if result.endswith('.webm'):
            mp3_path = result.replace('.webm', '.mp3')
            try:
                shutil.move(result, mp3_path)
                return mp3_path
            except:
                return result
        return result
    
    _module_logger.info("❌ All audio download methods failed")
    return None


async def download_video(link: str) -> str:
    """
    Main video download - Primary API -> Fallback API -> Worker Fallback API -> yt-dlp
    """
    # 1. TRY PRIMARY API FIRST
    _module_logger.info("🎬 Video Download - Trying Primary API (Direct)...")
    result = await download_video_primary_api(link)
    if result:
        _module_logger.info("✅ Video: Primary API Success")
        return result
    
    # 2. TRY FALLBACK API (TOKEN BASED)
    _module_logger.info("🔄 Video - Primary failed, trying Fallback API (Token)...")
    result = await download_video_fallback_api(link)
    if result:
        _module_logger.info("✅ Video: Fallback API Success")
        return result

    # 3. TRY WORKER FALLBACK API (DIRECT DOWNLOAD)
    _module_logger.info("🔄 Video - Fallback API failed, trying Worker Fallback API...")
    result = await download_video_worker_api(link)
    if result:
        _module_logger.info("✅ Video: Worker Fallback API Success")
        return result

    # 4. TRY YT-DLP AS LAST RESORT
    _module_logger.info("🔄 Video - All APIs failed, trying yt-dlp fallback...")
    result = await download_video_ytdlp(link)
    if result:
        _module_logger.info("✅ Video: yt-dlp Success")
        return result
    
    _module_logger.info("❌ All video download methods failed")
    return None


# ============ AUDIO: DIRECT STREAM URL ONLY (NO DISK DOWNLOAD) ============
# Per requirement: audio should never be downloaded to disk anymore — the
# player should always receive a direct, playable stream link. This is a
# small ordered chain of "stream URL providers"; each one either returns a
# ready-to-play URL or None. The first one that works wins.
#
# To add a brand new API later:
#   1. Write `async def _stream_url_newapi(link: str) -> Optional[str]: ...`
#      following the same shape as the ones below.
#   2. Append it to AUDIO_STREAM_SOURCES.
# Nothing else in the file needs to change.

async def _validate_stream_url(url: str, timeout: float = 6.0) -> bool:
    """
    Quick liveness check for a candidate stream URL before handing it to the
    player. Uses a tiny ranged GET (some CDNs ignore/block HEAD) so it never
    downloads the actual file — it only confirms the endpoint is alive and
    responds with a success status. Keeps the whole chain fast-failing so a
    dead API doesn't stall playback.
    """
    try:
        session = await _get_yt_session()
        headers = {"Range": "bytes=0-1"}
        async with session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            return resp.status in (200, 206)
    except Exception:
        return False


async def _stream_url_ytdlp(link: str) -> Optional[str]:
    """Direct googlevideo/CDN stream URL via `yt-dlp -g` — no file written."""
    await _check_rate_limit_async()
    ytdlp_args = [
        "yt-dlp", *(_yt_dlp_cli_args()), "--no-warnings", "--geo-bypass", "--force-ipv4",
        "-g", "-f", "bestaudio/best", link,
    ]
    stdout, stderr = await _exec_proc(*ytdlp_args)
    if stdout:
        url = stdout.decode().split("\n")[0].strip()
        if url.startswith("http"):
            return url
    error_msg = stderr.decode() if stderr else ""
    if _is_bot_check_error(error_msg):
        _module_logger.info(
            "❌ Stream (yt-dlp): YouTube bot-check triggered — cookies missing/expired."
        )
    elif "429" in error_msg or "Too Many Requests" in error_msg:
        _module_logger.info("❌ Stream (yt-dlp): rate limited (429).")
    return None


async def _stream_url_primary_api(link: str) -> Optional[str]:
    """
    Primary Shruti API's own endpoint used directly as the stream URL — the
    player pulls straight from the API's CDN instead of us downloading first.
    Only validated (ranged GET), never fully fetched here.
    """
    if not PRIMARY_API_URL:
        return None
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    if not video_id or len(video_id) < 3:
        return None
    url = f"{PRIMARY_API_URL}/download?url={video_id}&type=audio&api_key={SHRUTI_API_KEY}"
    return url if await _validate_stream_url(url) else None


async def _stream_url_worker_api(link: str) -> Optional[str]:
    """Worker (Cloudflare) fallback API's endpoint used directly as a stream URL."""
    if not WORKER_FALLBACK_API_URL:
        return None
    video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
    if not video_id or len(video_id) < 3:
        return None
    url = f"{WORKER_FALLBACK_API_URL}/download?url={video_id}&type=audio&key={WORKER_FALLBACK_API_KEY}"
    return url if await _validate_stream_url(url) else None


# NOTE: the token-based Fallback API (FALLBACK_API_URL) is intentionally left
# out of this chain — it requires a custom `X-Download-Token` header, which a
# plain stream URL can't carry, so it can't be handed to a player as-is.
AUDIO_STREAM_SOURCES = [
    _stream_url_ytdlp,
    _stream_url_primary_api,
    _stream_url_worker_api,
]


async def get_audio_stream_url(link: str) -> Optional[str]:
    """
    Tries each configured source in AUDIO_STREAM_SOURCES in order and returns
    the first working direct stream URL. No audio file is ever written to
    disk. If every source is down, returns None.
    """
    for source in AUDIO_STREAM_SOURCES:
        try:
            url = await source(link)
        except Exception as e:
            _module_logger.info(f"❌ Stream source '{source.__name__}' errored: {e}")
            continue
        if url:
            _module_logger.info(f"✅ Audio stream URL via {source.__name__}")
            return url
    return None


# ============ YOUTUBE DATA API v3 (SEARCH) ============
# Normalizes results into the same shape youtubesearchpython used to return
# ({"id", "title", "duration", "thumbnails": [{"url": ...}], "link", "channel"})
# so every existing consumer below (title/duration/thumbnail/details/track/
# slider) keeps working unchanged.

_ISO8601_DUR_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def _iso8601_duration_to_str(iso: Optional[str]) -> Optional[str]:
    """Convert YouTube's 'PT#H#M#S' duration into 'M:SS' / 'H:MM:SS' text,
    matching youtubesearchpython's old string format. Live streams report
    durations like 'P0D' (no time component) -> treated as None, same as
    youtubesearchpython did for ongoing livestreams."""
    if not iso:
        return None
    m = _ISO8601_DUR_RE.match(iso)
    if not m:
        return None
    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0) + days * 24
    minutes = int(m.group("minutes") or 0)
    seconds = int(m.group("seconds") or 0)
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        return None
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _log_v3_error_body(context: str, status: int, body: str, key: Optional[str] = None) -> Optional[str]:
    """
    Parses the standard Google API error JSON and logs the REAL reason
    (quota exceeded, key invalid, API not enabled, referrer blocked, etc.)
    instead of just the raw HTTP status, which is what actually matters
    when V3 API calls stop working. Returns the parsed `reason` string
    (e.g. 'quotaExceeded') so callers can react to it programmatically —
    used to trigger key rotation / the yt-dlp search fallback below.
    """
    reason = None
    message = None
    try:
        parsed = json.loads(body)
        err = parsed.get("error", {})
        message = err.get("message")
        errors_list = err.get("errors") or []
        if errors_list:
            reason = errors_list[0].get("reason")
        reason = reason or err.get("status")
    except Exception:
        pass

    if status == 403:
        if reason == "quotaExceeded":
            hint = (
                "reason='quotaExceeded' -> this key's daily YouTube Data API v3 quota "
                "(10,000 units/day on the default free tier) is used up; "
                "it resets at midnight Pacific time. Rotating to next key if available. "
            )
        elif reason in ("keyInvalid", "accessNotConfigured", "forbidden"):
            hint = (
                "-> check the API key is correct, that 'YouTube Data API v3' is ENABLED "
                "for this project in Google Cloud Console, and that any API-key "
                "restrictions (HTTP referrer / IP / API restrictions) allow this server. "
            )
        else:
            hint = ""
    elif status == 400:
        hint = "reason='badRequest' -> malformed request (bad key format or bad params). "
    elif status == 429:
        hint = "-> rate limited by Google, back off. "
    else:
        hint = ""

    _module_logger.error(
        f"❌ YouTube V3 {context} failed: HTTP {status} reason={reason} "
        f"message={message!r} key={_mask_key(key)} | {hint}raw={body[:500]}"
    )
    return reason



# ── YouTube V3 quota-exhaustion tracking + multi-key rotation + automatic
#    yt-dlp search fallback ─────────────────────────────────────────────────
# Once Google returns reason='quotaExceeded' for a key, every further call
# with THAT key would just fail the same way until midnight Pacific. Instead
# of hammering Google with doomed requests:
#   1. Mark only that one key exhausted (with its own reset time) and rotate
#      to the next key in YOUTUBE_API_KEYS — so a single key running out
#      doesn't stop the bot.
#   2. Only once EVERY key in the pool is simultaneously exhausted do we shift
#      to the quota-free yt-dlp search fallback, until the earliest key resets.
_V3_QUOTA_EXCEEDED_UNTIL = 0.0  # epoch seconds; 0 = at least one key believed OK


def _seconds_until_pt_midnight() -> float:
    """How many seconds until the next YouTube API quota reset (midnight
    Pacific time). Falls back to a flat 1-hour retry if timezone data isn't
    available, so we still recover instead of being stuck forever."""
    if ZoneInfo is None:
        return 3600.0
    try:
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime.now(tz)
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return max((next_midnight - now).total_seconds(), 60.0)
    except Exception:
        return 3600.0


async def _get_active_api_key() -> Optional[str]:
    """
    Returns the next YouTube API key that isn't currently marked
    quota-exhausted, rotating round-robin through YOUTUBE_API_KEYS. Returns
    None only when every single key in the pool is exhausted right now —
    that's the signal to use the yt-dlp fallback instead.
    """
    global _current_key_idx
    if not YOUTUBE_API_KEYS:
        return None
    now = time.time()
    async with _key_rotation_lock:
        n = len(YOUTUBE_API_KEYS)
        for step in range(n):
            idx = (_current_key_idx + step) % n
            key = YOUTUBE_API_KEYS[idx]
            if now >= _key_exhausted_until.get(key, 0.0):
                _current_key_idx = idx
                return key
    return None  # every key in the pool is currently exhausted


async def _mark_key_quota_exceeded(key: str) -> None:
    """Marks ONE key exhausted until midnight PT and rotates to the next one.
    Only sets the global all-keys-exhausted fallback flag once no key in the
    pool is usable anymore."""
    global _current_key_idx, _V3_QUOTA_EXCEEDED_UNTIL
    reset_at = time.time() + _seconds_until_pt_midnight()
    async with _key_rotation_lock:
        _key_exhausted_until[key] = reset_at
        _current_key_idx = (_current_key_idx + 1) % len(YOUTUBE_API_KEYS)
        remaining = [k for k in YOUTUBE_API_KEYS if time.time() >= _key_exhausted_until.get(k, 0.0)]

    if remaining:
        _module_logger.warning(
            f"⏭️ YouTube V3 key {_mask_key(key)} quota exhausted — rotating to another "
            f"key ({len(remaining)}/{len(YOUTUBE_API_KEYS)} keys still available)."
        )
    else:
        _V3_QUOTA_EXCEEDED_UNTIL = min(_key_exhausted_until.values())
        _module_logger.warning(
            f"⏭️ ALL {len(YOUTUBE_API_KEYS)} YouTube V3 key(s) quota exhausted — shifting "
            f"all search to the yt-dlp fallback for ~"
            f"{(_V3_QUOTA_EXCEEDED_UNTIL - time.time()) / 3600:.1f}h (until the earliest "
            f"key resets at midnight Pacific)."
        )



async def _ytdlp_search_fallback(query: str, limit: int = 1) -> List[Dict]:
    """
    Fallback search used whenever YouTube Data API v3 is unavailable — quota
    exhausted, key invalid/missing, network error, timeout, etc. Uses
    yt-dlp's built-in `ytsearch` (no API key / quota needed) so search keeps
    working uninterrupted. Runs the blocking yt-dlp extraction in a thread
    executor. Returns results normalized to the exact same shape as
    _youtube_v3_search so every downstream consumer keeps working unchanged.
    """
    if not query or not query.strip():
        return []
    n = min(max(limit, 1), 20)

    def _extract():
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}},
        }
        cf = _cookiefile_path()
        if cf:
            opts["cookiefile"] = cf
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
            return (info or {}).get("entries", []) or []

    try:
        entries = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _extract), timeout=20
        )
    except Exception as e:
        _module_logger.error(f"❌ yt-dlp search fallback failed: {type(e).__name__}: {e} | q={query!r}")
        return []

    results: List[Dict] = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id")
        if not vid:
            continue
        dur_sec = e.get("duration")
        duration_str = None
        if dur_sec:
            dur_sec = int(dur_sec)
            hours, rem = divmod(dur_sec, 3600)
            minutes, seconds = divmod(rem, 60)
            duration_str = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
        thumbs = e.get("thumbnails") or []
        thumb_url = thumbs[-1].get("url", "") if thumbs else ""
        results.append({
            "id": vid,
            "title": e.get("title", ""),
            "duration": duration_str,
            "thumbnails": [{"url": thumb_url}],
            "thumbnail": thumb_url,
            "link": f"https://www.youtube.com/watch?v={vid}",
            "channel": {"name": e.get("channel") or e.get("uploader") or ""},
        })

    if results:
        _module_logger.info(f"✅ yt-dlp search fallback OK — {len(results)} item(s) for q={query!r}")
    else:
        _module_logger.warning(f"⚠️ yt-dlp search fallback: 0 results for q={query!r}")
    return results


async def _youtube_v3_video_durations(video_ids: List[str]) -> Dict[str, Optional[str]]:
    """Batch-fetch contentDetails.duration for up to 50 video IDs in one call.

    BUG FIX: this used to try exactly one key and give up on ANY failure
    (invalid key, transient error, etc.) without ever trying the rest of the
    key pool — unlike _youtube_v3_search, which does rotate. It now rotates
    through every configured key the same way search does, so a single bad
    key here no longer silently kills durations for every search result."""
    if not video_ids:
        return {}
    session = await _get_yt_session()
    global _current_key_idx

    for attempt in range(max(len(YOUTUBE_API_KEYS), 1)):
        api_key = await _get_active_api_key()
        if not api_key:
            _module_logger.error("❌ YouTube V3 videos.list skipped: no non-exhausted API key available.")
            return {}
        try:
            async with session.get(
                f"{YOUTUBE_V3_BASE_URL}/videos",
                params={
                    "part": "contentDetails",
                    "id": ",".join(video_ids[:50]),
                    "key": api_key,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    reason = _log_v3_error_body("videos.list", response.status, body, key=api_key)
                    if reason == "quotaExceeded":
                        await _mark_key_quota_exceeded(api_key)
                    else:
                        async with _key_rotation_lock:
                            _current_key_idx = (_current_key_idx + 1) % len(YOUTUBE_API_KEYS)
                        _module_logger.warning(
                            f"↩️ Key {_mask_key(api_key)} failed on videos.list (reason={reason}) — trying next key."
                        )
                    continue
                data = await response.json()
                break
        except asyncio.TimeoutError:
            _module_logger.error("❌ YouTube V3 videos.list error: request timed out after 10s.")
            return {}
        except aiohttp.ClientError as e:
            _module_logger.error(f"❌ YouTube V3 videos.list network error: {type(e).__name__}: {e}")
            return {}
        except Exception as e:
            _module_logger.error(f"❌ YouTube V3 videos.list unexpected error: {type(e).__name__}: {e}")
            return {}
    else:
        _module_logger.warning("↩️ All keys failed on videos.list — returning no durations for this batch.")
        return {}

    out: Dict[str, Optional[str]] = {}
    for item in data.get("items", []):
        vid = item.get("id")
        iso = item.get("contentDetails", {}).get("duration")
        out[vid] = _iso8601_duration_to_str(iso)
    _module_logger.info(f"✅ YouTube V3 videos.list OK — {len(out)}/{len(video_ids)} durations fetched.")
    return out


async def _youtube_v3_search(query: str, limit: int = 1) -> List[Dict]:
    """Official YouTube Data v3 search.search + videos.list (for durations),
    returned as a list of normalized dicts (see module docstring above).

    Rotates through every key in YOUTUBE_API_KEYS before giving up, and only
    once ALL keys are exhausted (or missing) does it shift to
    _ytdlp_search_fallback() — so search never just stops working. Callers
    don't need to know or care which key/backend actually served the result."""
    global _current_key_idx
    if not query or not query.strip():
        return []

    now = time.time()
    if now < _V3_QUOTA_EXCEEDED_UNTIL:
        remaining_h = (_V3_QUOTA_EXCEEDED_UNTIL - now) / 3600
        _module_logger.info(
            f"⏭️ All YouTube V3 keys still exhausted (~{remaining_h:.1f}h until earliest "
            f"reset) — using yt-dlp search fallback directly. q={query!r}"
        )
        return await _ytdlp_search_fallback(query, limit)

    await _check_rate_limit_async()
    session = await _get_yt_session()

    for attempt in range(max(len(YOUTUBE_API_KEYS), 1)):
        api_key = await _get_active_api_key()
        if not api_key:
            _module_logger.error(
                "❌ YouTube V3 search: no non-exhausted API key available. "
                "Shifting to yt-dlp search fallback."
            )
            return await _ytdlp_search_fallback(query, limit)

        _module_logger.info(
            f"🔎 YouTube V3 search: q={query!r} limit={limit} key={_mask_key(api_key)} "
            f"(attempt {attempt + 1}/{len(YOUTUBE_API_KEYS)})"
        )
        try:
            async with session.get(
                f"{YOUTUBE_V3_BASE_URL}/search",
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "maxResults": min(max(limit, 1), 50),
                    "key": api_key,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    reason = _log_v3_error_body("search.search", response.status, body, key=api_key)
                    if reason == "quotaExceeded":
                        await _mark_key_quota_exceeded(api_key)
                    else:
                        # BUG FIX: previously any non-quota error (invalid key,
                        # accessNotConfigured, a transient 5xx from Google,
                        # etc.) gave up on the ENTIRE key pool immediately and
                        # fell back to yt-dlp — even if other configured keys
                        # were perfectly fine. Now we just rotate past this
                        # one bad key and keep trying the rest of the pool.
                        async with _key_rotation_lock:
                            _current_key_idx = (_current_key_idx + 1) % len(YOUTUBE_API_KEYS)
                        _module_logger.warning(
                            f"↩️ Key {_mask_key(api_key)} failed (reason={reason}) — "
                            f"trying next key in the pool instead of giving up."
                        )
                    continue  # try the next key in the pool right away
                data = await response.json()
                break
        except asyncio.TimeoutError:
            _module_logger.error(f"❌ YouTube V3 search error: request timed out after 10s. q={query!r}")
            return await _ytdlp_search_fallback(query, limit)
        except aiohttp.ClientError as e:
            _module_logger.error(f"❌ YouTube V3 search network error: {type(e).__name__}: {e} | q={query!r}")
            return await _ytdlp_search_fallback(query, limit)
        except Exception as e:
            _module_logger.error(f"❌ YouTube V3 search unexpected error: {type(e).__name__}: {e} | q={query!r}")
            return await _ytdlp_search_fallback(query, limit)
    else:
        # Every key in the pool failed during this loop (quota or otherwise).
        _module_logger.warning(f"↩️ All keys failed — shifting to yt-dlp search fallback for q={query!r}")
        return await _ytdlp_search_fallback(query, limit)

    items = data.get("items", [])
    if not items:
        # A genuine "no results" from a healthy API call — not a failure, so
        # no fallback needed here (the fallback wouldn't find anything either).
        _module_logger.warning(f"⚠️ YouTube V3 search: 0 items returned for q={query!r} (not an error, just no results).")
        return []
    _module_logger.info(f"✅ YouTube V3 search OK — {len(items)} item(s) for q={query!r}")

    video_ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
    durations = await _youtube_v3_video_durations(video_ids)

    results: List[Dict] = []
    for it in items:
        vid = it.get("id", {}).get("videoId")
        if not vid:
            continue
        snippet = it.get("snippet", {})
        thumbs = snippet.get("thumbnails", {})
        thumb_url = (
            thumbs.get("high", {}).get("url")
            or thumbs.get("medium", {}).get("url")
            or thumbs.get("default", {}).get("url")
            or ""
        )
        results.append({
            "id": vid,
            "title": snippet.get("title", ""),
            "duration": durations.get(vid),
            "thumbnails": [{"url": thumb_url}],
            "thumbnail": thumb_url,
            "link": f"https://www.youtube.com/watch?v={vid}",
            "channel": {"name": snippet.get("channelTitle", "")},
        })
    return results


# ============ YOUTUBE API CLASS ============
@capture_internal_err
async def cached_youtube_search(query: str) -> List[Dict]:
    key = f"q:{query}"
    now = time.time()
    async with _cache_lock:
        if key in _cache:
            ts, val = _cache[key]
            if now - ts < YOUTUBE_META_TTL:
                return val
            _cache.pop(key, None)
        if len(_cache) > YOUTUBE_META_MAX:
            _cache.clear()
    try:
        result = await _youtube_v3_search(query, limit=1)
    except Exception:
        result = []
    if result:
        async with _cache_lock:
            _cache[key] = (now, result)
    return result


@capture_internal_err
async def youtube_search_multi(query: str, limit: int = 8) -> List[Dict]:
    """
    Fetch multiple YouTube results for a query â€” used by autoplay so it can
    score and pick from a pool of candidates rather than always getting the
    same #1 result. Results are NOT cached (we want variety across calls).
    """
    try:
        return await _youtube_v3_search(query, limit=limit)
    except Exception:
        return []

async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, errorz = await proc.communicate()
    if errorz:
        if "unavailable videos are hidden" in (errorz.decode("utf-8")).lower():
            return out.decode("utf-8")
        else:
            return errorz.decode("utf-8")
    return out.decode("utf-8")

class YouTubeAPI:
    def __init__(self) -> None:
        self.base_url = "https://www.youtube.com/watch?v="
        self.playlist_url = "https://youtube.com/playlist?list="
        self.status = "https://www.youtube.com/oembed?url="
        self._url_pattern = re.compile(r"(?:youtube\.com|youtu\.be)")
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    def _prepare_link(self, link: str, videoid: Union[str, bool, None] = None) -> str:
        if isinstance(videoid, str) and videoid.strip():
            link = self.base_url + videoid.strip()
        if "youtu.be" in link:
            link = self.base_url + link.split("/")[-1].split("?")[0]
        elif "youtube.com/shorts/" in link or "youtube.com/live/" in link:
            link = self.base_url + link.split("/")[-1].split("?")[0]
        return link.split("&")[0]

    @capture_internal_err
    async def url(self, message: Message) -> Optional[str]:
        msgs = [message] + ([message.reply_to_message] if message.reply_to_message else [])
        for msg in msgs:
            text = msg.text or msg.caption or ""
            entities = msg.entities or msg.caption_entities or []
            for ent in entities:
                if ent.type == MessageEntityType.URL:
                    url = text[ent.offset : ent.offset + ent.length]
                    if self._url_pattern.search(url):
                        return url
                if ent.type == MessageEntityType.TEXT_LINK:
                    url = ent.url
                    if self._url_pattern.search(url):
                        return url
        return None

    @capture_internal_err
    async def exists(self, link: str, videoid: Union[str, bool, None] = None) -> bool:
        return bool(self._url_pattern.search(self._prepare_link(link, videoid)))

    @capture_internal_err
    async def _fetch_video_info(self, query: str, *, use_cache: bool = True) -> Optional[Dict]:
        q = self._prepare_link(query)
        if use_cache and not q.startswith("http"):
            res = await cached_youtube_search(q)
            return res[0] if res else None
        result = await _youtube_v3_search(q, limit=1)
        return result[0] if result else None

    @capture_internal_err
    async def is_live(self, link: str) -> bool:
        await _check_rate_limit_async()
        prepared = self._prepare_link(link)
        stdout, _ = await _exec_proc("yt-dlp", *(_yt_dlp_cli_args()), "--dump-json", prepared)
        if not stdout:
            return False
        try:
            info = json.loads(stdout.decode())
            return bool(info.get("is_live"))
        except json.JSONDecodeError:
            return False

    @capture_internal_err
    async def details(self, link: str, videoid: Union[str, bool, None] = None) -> Tuple[str, Optional[str], int, str, str]:
        info = await self._fetch_video_info(self._prepare_link(link, videoid))
        if not info:
            raise ValueError("Video not found")
        dt = info.get("duration")
        ds = int(time_to_seconds(dt)) if dt else 0
        thumb = (info.get("thumbnail") or info.get("thumbnails", [{}])[0].get("url", "")).split("?")[0]
        return info.get("title", ""), dt, ds, thumb, info.get("id", "")

    @capture_internal_err
    async def title(self, link: str, videoid: Union[str, bool, None] = None) -> str:
        info = await self._fetch_video_info(self._prepare_link(link, videoid))
        return info.get("title", "") if info else ""

    @capture_internal_err
    async def duration(self, link: str, videoid: Union[str, bool, None] = None) -> Optional[str]:
        info = await self._fetch_video_info(self._prepare_link(link, videoid))
        return info.get("duration") if info else None

    @capture_internal_err
    async def thumbnail(self, link: str, videoid: Union[str, bool, None] = None) -> str:
        info = await self._fetch_video_info(self._prepare_link(link, videoid))
        if info:
            thumb = info.get("thumbnail") or info.get("thumbnails", [{}])[0].get("url", "")
            return thumb.split("?")[0] if thumb else ""
        return ""

    @capture_internal_err
    async def video(self, link: str, videoid: Union[str, bool, None] = None) -> Tuple[int, str]:
        link = self._prepare_link(link, videoid)
        
        try:
            downloaded_file = await download_video(link)
            if downloaded_file:
                return (1, downloaded_file)
        except Exception:
            pass
        
        await _check_rate_limit_async()
        
        ytdlp_args = [
            "yt-dlp", *(_yt_dlp_cli_args()), "--no-warnings", "--geo-bypass", "--force-ipv4",
            "-g", "-f", "best[height<=?720][width<=?1280]/best", link
        ]
        
        stdout, stderr = await _exec_proc(*ytdlp_args)
        
        if stdout:
            stream_url = stdout.decode().split("\n")[0]
            if stream_url and stream_url.startswith('http'):
                return (1, stream_url)
            else:
                return (0, "Invalid stream URL")
        else:
            error_msg = stderr.decode() if stderr else "Unknown error"
            if _is_bot_check_error(error_msg):
                _module_logger.info(
                    "❌ YouTube bot-check triggered — cookies are missing/expired. "
                    "Export fresh cookies (yt-dlp --cookies-from-browser) and update COOKIE_PATH."
                )
                return (0, "YouTube requires sign-in (cookies missing/expired)")
            if "429" in error_msg or "Too Many Requests" in error_msg:
                await asyncio.sleep(30)
                return (0, "Rate limited")
            elif "403" in error_msg:
                return await self._try_alternative_format(link)
            else:
                return (0, error_msg)

    async def _try_alternative_format(self, link: str) -> Tuple[int, str]:
        format_options = ["best[height<=480]", "best[ext=mp4]", "best", "worst"]
        for fmt in format_options:
            stdout, stderr = await _exec_proc("yt-dlp", *(_yt_dlp_cli_args()), "--no-warnings", "-g", "-f", fmt, link)
            if stdout:
                stream_url = stdout.decode().split("\n")[0]
                if stream_url and stream_url.startswith('http'):
                    return (1, stream_url)
            await asyncio.sleep(1)
        return (0, "All format attempts failed")

    @capture_internal_err
    async def playlist(self, link: str, limit: int, user_id, videoid: Union[str, bool, None] = None) -> List[str]:
        if videoid:
            link = self.playlist_url + str(videoid)
        link = link.split("&")[0]
        await _check_rate_limit_async()
        extra = " ".join(_yt_dlp_cli_args())
        playlist = await shell_cmd(f"yt-dlp -i --get-id --flat-playlist --playlist-end {limit} --skip-download {extra} {link}")
        try:
            items = [key for key in playlist.split("\n") if key]
        except:
            items = []
        return items

    @capture_internal_err
    async def track(self, link: str, videoid: Union[str, bool, None] = None) -> Tuple[Dict, str]:
        try:
            info = await self._fetch_video_info(self._prepare_link(link, videoid))
            if not info:
                raise ValueError("Track not found via API")
        except Exception:
            await _check_rate_limit_async()
            prepared = self._prepare_link(link, videoid)
            stdout, _ = await _exec_proc("yt-dlp", *(_yt_dlp_cli_args()), "--dump-json", prepared)
            if not stdout:
                raise ValueError("Track not found (yt-dlp fallback)")
            info = json.loads(stdout.decode())
        thumb = (info.get("thumbnail") or info.get("thumbnails", [{}])[0].get("url", "")).split("?")[0]
        _dur = info.get("duration")
        if isinstance(_dur, str) and _dur:
            duration_min = _dur
        elif isinstance(_dur, (int, float)) and _dur > 0:
            _secs = int(_dur)
            duration_min = f"{_secs // 60}:{_secs % 60:02d}"
        else:
            duration_min = None
        details = {
            "title": info.get("title", ""),
            "link": info.get("webpage_url", self._prepare_link(link, videoid)),
            "vidid": info.get("id", ""),
            "duration_min": duration_min,
            "thumb": thumb,
        }
        return details, info.get("id", "")

    @capture_internal_err
    async def formats(self, link: str, videoid: Union[str, bool, None] = None) -> Tuple[List[Dict], str]:
        link = self._prepare_link(link, videoid)
        key = f"f:{link}"
        now = time.time()
        async with _formats_lock:
            cached = _formats_cache.get(key)
            if cached and now - cached[0] < YOUTUBE_META_TTL:
                return cached[1], cached[2]

        await _check_rate_limit_async()
        
        opts = {
            "quiet": True,
            "extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}},
        }
        cf = _cookiefile_path()
        if cf:
            opts["cookiefile"] = cf
        out: List[Dict] = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(link, download=False)
                for fmt in info.get("formats", []):
                    if "dash" in str(fmt.get("format", "")).lower():
                        continue
                    if not any(k in fmt for k in ("filesize", "filesize_approx")):
                        continue
                    if not all(k in fmt for k in ("format", "format_id", "ext", "format_note")):
                        continue
                    size = fmt.get("filesize") or fmt.get("filesize_approx")
                    if not size:
                        continue
                    out.append({
                        "format": fmt["format"],
                        "filesize": size,
                        "format_id": fmt["format_id"],
                        "ext": fmt["ext"],
                        "format_note": fmt["format_note"],
                        "yturl": link,
                    })
        except Exception:
            pass

        async with _formats_lock:
            if len(_formats_cache) > YOUTUBE_META_MAX:
                _formats_cache.clear()
            _formats_cache[key] = (now, out, link)

        return out, link

    @capture_internal_err
    async def slider(self, link: str, query_type: int, videoid: Union[str, bool, None] = None) -> Tuple[str, Optional[str], str, str]:
        results = await _youtube_v3_search(self._prepare_link(link, videoid), limit=10)
        if not results or query_type >= len(results):
            raise IndexError(f"Query type index {query_type} out of range (found {len(results)} results)")
        r = results[query_type]
        return (
            r.get("title", ""),
            r.get("duration"),
            r.get("thumbnails", [{}])[0].get("url", "").split("?")[0],
            r.get("id", ""),
        )

    @capture_internal_err
    async def download(
        self,
        link: str,
        mystic,
        *,
        video: Union[bool, str, None] = None,
        videoid: Union[str, bool, None] = None,
        songaudio: Union[bool, str, None] = None,
        songvideo: Union[bool, str, None] = None,
        format_id: Union[bool, str, None] = None,
        title: Union[bool, str, None] = None,
    ) -> Union[Tuple[str, Optional[bool]], Tuple[None, None]]:
        link = self._prepare_link(link, videoid)
        video_id = link.split('v=')[-1].split('&')[0] if 'v=' in link else link
        
        extension = ".webm" if not video else ".mp4"
        common_file_path = os.path.join("downloads", f"{video_id}{extension}")
        
        if os.path.exists(common_file_path) and os.path.getsize(common_file_path) > 10240:
            _module_logger.info("✅ Local cache")
            return common_file_path, True

        if songvideo or video:
            try:
                downloaded_file = await download_video(link)
                if downloaded_file:
                    _module_logger.info("✅ Video downloaded successfully")
                    if downloaded_file != common_file_path and downloaded_file.endswith('.mp4'):
                        try:
                            shutil.move(downloaded_file, common_file_path)
                            return common_file_path, True
                        except Exception:
                            return downloaded_file, True
                    return downloaded_file, True
            except Exception as e:
                _module_logger.info(f"❌ Video download error: {str(e)}")
            
            status, stream_url = await self.video(link)
            if status == 1:
                _module_logger.info("✅ Video stream")
                return stream_url, None
            else:
                return None, None

        else:
            # ── AUDIO: STREAM ONLY, NEVER DOWNLOADED TO DISK ──
            # No file is written for audio anymore. get_audio_stream_url() walks
            # AUDIO_STREAM_SOURCES (yt-dlp -g -> Primary API URL -> Worker API
            # URL, in that order) and returns the first live, playable link.
            # Returning (url, None) matches the existing convention: `True`
            # means "local file path", `None` means "remote stream URL".
            stream_url = await get_audio_stream_url(link)
            if stream_url:
                _module_logger.info("✅ Audio stream URL ready (no download)")
                return stream_url, None

            _module_logger.info("❌ All audio stream sources failed")
            return None, None

YouTube = YouTubeAPI()

# ═══════════════════════════════════════════════════════════
#        😎  VISHAL MUSIC BOT  😎
#   github.com/ItsMeVishal0/VishalMusic
# ═══════════════════════════════════════════════════════════
