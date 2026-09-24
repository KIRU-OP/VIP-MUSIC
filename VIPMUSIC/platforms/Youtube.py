import asyncio
import json
import os
import re
from typing import List, Union
import yt_dlp
import aiohttp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from py_yt import VideosSearch, Playlist

# Pyrogram bot client, used to upload/fetch cached songs from the cache
# channel below. Adjust this import to match how your bot's Client
# instance is actually exposed (e.g. `from YourBot import app`).
from codex import app

API_URL = os.environ.get("MEOW_API_URL", "https://music.yukiapi.site")
API_KEY = os.environ.get("MEOW_API_KEY", "yuki_7df1554f161bfa6ac85a56d3ba917f36")  # 🔑 Get Key: @MeowApiRobot On Telegram

# Fallback resolver (Cloudflare Worker). Used only when the primary MEOW API
# fails (non-200 response, timeout, empty file, etc).
WORKER_FALLBACK_API_URL = os.getenv(
    "WORKER_FALLBACK_API_URL",
    "https://youtubenewapi.skybotsdeveloper.workers.dev",
).strip().rstrip("/")
WORKER_FALLBACK_API_KEY = os.getenv("WORKER_FALLBACK_API_KEY", "itsmesid").strip()
# Path template for the worker's download endpoint — change via env if the
# worker uses a different route. {video_id} is replaced automatically.
WORKER_FALLBACK_PATH = os.getenv("WORKER_FALLBACK_PATH", "/stream/{video_id}").strip()

DOWNLOAD_DIR = "downloads"

# ---------------------------------------------------------------------------
# Song cache channel
# ---------------------------------------------------------------------------
# Every song that gets downloaded is uploaded once to this channel, and its
# Telegram file_id is remembered locally. The next time the same song is
# requested, it's pulled straight from Telegram instead of being
# re-downloaded from the source API — much faster, and saves bandwidth/quota.
#
# Setup:
#   1. Add your bot as an ADMIN of the channel/group at
#      https://t.me/+vbG1ayQcjWtiOTE9
#   2. Get that chat's numeric id (forward any message from it to
#      @userinfobot, or log update.chat.id the first time the bot sees a
#      message from it) — an invite link alone isn't enough, Telegram's Bot
#      API needs the numeric chat_id (looks like -100XXXXXXXXXX).
#   3. Set it as an env var: export CACHE_CHANNEL_ID="-100XXXXXXXXXX"
CACHE_CHANNEL_ID = int(os.environ.get("CACHE_CHANNEL_ID", "-1004486298204") or "0")

_SONG_CACHE_FILE = "song_cache.json"
_cache_lock = asyncio.Lock()


def _load_song_cache() -> dict:
    if os.path.exists(_SONG_CACHE_FILE):
        try:
            with open(_SONG_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_song_cache(cache: dict):
    try:
        with open(_SONG_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


_SONG_CACHE = _load_song_cache()


async def _get_cached_entry(video_id: str, kind: str):
    """kind is 'audio' or 'video' — each is cached separately since they're
    different Telegram file_ids."""
    entry = _SONG_CACHE.get(video_id)
    if entry:
        return entry.get(kind)
    return None


async def _download_thumb(thumbnail_url: str, video_id: str) -> Union[str, None]:
    if not thumbnail_url:
        return None
    thumb_path = os.path.join(DOWNLOAD_DIR, f"{video_id}_thumb.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                with open(thumb_path, "wb") as f:
                    f.write(await resp.read())
        return thumb_path
    except Exception:
        return None


_cache_queue: "asyncio.Queue" = asyncio.Queue()
_cache_worker_started = False


def start_cache_worker():
    """Starts the background worker that keeps pushing every played song
    into the cache channel, one at a time. Call this ONCE at bot startup
    (e.g. right after you start your Pyrogram Client), from inside a
    running event loop:

        from RishuMusic.platforms.Youtube import start_cache_worker
        start_cache_worker()

    Without this the queue still fills up, it just never drains — songs
    would download fine but never get pushed to the channel."""
    global _cache_worker_started
    if _cache_worker_started:
        return
    _cache_worker_started = True
    asyncio.get_event_loop().create_task(_cache_worker())


async def _cache_worker():
    """Runs forever in the background, processing one queued song at a
    time so the group's playback is never blocked and Telegram doesn't
    rate-limit the bot from too many parallel uploads."""
    while True:
        video_id, file_path, kind = await _cache_queue.get()
        try:
            await _upload_to_cache_channel(video_id, file_path, kind)
        except Exception:
            pass
        finally:
            _cache_queue.task_done()


def queue_for_caching(video_id: str, file_path: str, kind: str):
    """Drops a freshly-downloaded song/video onto the background queue so
    the worker uploads it to the cache channel without delaying playback."""
    if not CACHE_CHANNEL_ID:
        return
    start_cache_worker()  # lazy-start as a safety net if not started at boot
    _cache_queue.put_nowait((video_id, file_path, kind))


async def _upload_to_cache_channel(video_id: str, file_path: str, kind: str):
    """Uploads one song/video to the cache channel and remembers its
    file_id for next time. Called only by _cache_worker — don't call this
    directly from playback code, use queue_for_caching() instead."""
    if not CACHE_CHANNEL_ID:
        return
    thumb_path = None
    try:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        results = await _v3_search(video_id, limit=1)
        title = results[0]["title"] if results else video_id
        duration = results[0]["duration_min"] if results else ""
        thumb_url = results[0]["thumbnail"] if results else ""
        thumb_path = await _download_thumb(thumb_url, video_id)

        caption = f"{title}\n{duration}\nhttps://www.youtube.com/watch?v={video_id}"
        if kind == "video":
            sent = await app.send_video(
                chat_id=CACHE_CHANNEL_ID,
                video=file_path,
                caption=caption,
                thumb=thumb_path,
            )
            file_id = sent.video.file_id
        else:
            sent = await app.send_audio(
                chat_id=CACHE_CHANNEL_ID,
                audio=file_path,
                caption=caption,
                title=title,
                thumb=thumb_path,
            )
            file_id = sent.audio.file_id

        async with _cache_lock:
            entry = _SONG_CACHE.get(video_id, {})
            entry[kind] = file_id
            entry["title"] = title
            _SONG_CACHE[video_id] = entry
            _save_song_cache(_SONG_CACHE)
    except Exception:
        pass
    finally:
        if thumb_path and os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except Exception:
                pass

# ---------------------------------------------------------------------------
# YouTube Data API v3 — key pool
# ---------------------------------------------------------------------------
# Set ONE OR MORE keys as a comma-separated env var, e.g.:
#   export YOUTUBE_API_KEYS="key1,key2,key3"
#
# Do NOT hardcode real keys in this file. Keys committed to source control
# (even in a private repo) get scraped and abused within hours, and Google
# will revoke them the moment that happens.
#
# QUOTA NOTE: each key gives ~10,000 units/day (a search ≈ 100 units). The
# pool below rotates to the next key on quotaExceeded, so effective daily
# quota = 10,000 × number of keys. Only when every key is exhausted does it
# fall back to a quota-free yt-dlp search (see _ytdlp_search_fallback).
_raw_keys = os.environ.get("YOUTUBE_API_KEYS", "AIzaSyAuWd41xKkkd0HDq87dK9jHffW6lKzKWJs, AIzaSyBT9ffbKLBhRQDr8WWt3IH4FcXqenFjoO0, AIzaSyB3Mf15uCZ3oqpWRRScj9jxDt0WUI0YYJc").strip()
YOUTUBE_API_KEYS: List[str] = [k.strip() for k in _raw_keys.split(",") if k.strip()]

YOUTUBE_V3_BASE_URL = "https://www.googleapis.com/youtube/v3"

_key_index_lock = asyncio.Lock()
_current_key_index = 0


def time_to_seconds(time):
    stringt = str(time)
    return sum(int(x) * 60 ** i for i, x in enumerate(reversed(stringt.split(":"))))


async def _get_current_key() -> Union[str, None]:
    if not YOUTUBE_API_KEYS:
        return None
    async with _key_index_lock:
        if _current_key_index >= len(YOUTUBE_API_KEYS):
            return None
        return YOUTUBE_API_KEYS[_current_key_index]


async def _rotate_key() -> bool:
    """Advance to the next key. Returns False if the pool is exhausted."""
    global _current_key_index
    async with _key_index_lock:
        _current_key_index += 1
        return _current_key_index < len(YOUTUBE_API_KEYS)


async def _reset_key_pool():
    global _current_key_index
    async with _key_index_lock:
        _current_key_index = 0


def _is_quota_error(status: int, payload: dict) -> bool:
    if status == 403:
        reasons = {
            err.get("reason")
            for err in (payload.get("error", {}).get("errors", []) or [])
        }
        if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
            return True
    return False


async def _v3_get(session: aiohttp.ClientSession, endpoint: str, params: dict):
    """
    Calls a YouTube Data API v3 endpoint, rotating keys on quota errors.
    Returns the parsed JSON dict, or None if every key is exhausted / call fails.
    """
    if not YOUTUBE_API_KEYS:
        return None

    tries = len(YOUTUBE_API_KEYS)
    for _ in range(tries):
        key = await _get_current_key()
        if key is None:
            return None
        request_params = dict(params)
        request_params["key"] = key
        url = f"{YOUTUBE_V3_BASE_URL}/{endpoint}"
        try:
            async with session.get(url, params=request_params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status == 200:
                    return data
                if _is_quota_error(resp.status, data):
                    has_more = await _rotate_key()
                    if not has_more:
                        return None
                    continue
                # Non-quota error (bad request, disabled API, etc.) — no point rotating.
                return None
        except Exception:
            return None
    return None


def _seconds_to_min_str(seconds: int) -> str:
    if not seconds:
        return "0:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _iso8601_duration_to_seconds(duration: str) -> int:
    # e.g. "PT4M13S" -> 253
    match = re.match(
        r"PT(?:(\d+)D)?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or ""
    )
    if not match:
        return 0
    days, hours, minutes, secs = (int(x) if x else 0 for x in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + secs


def _extract_video_id_from_query(query: str) -> Union[str, None]:
    if "v=" in query:
        return query.split("v=")[-1].split("&")[0]
    if "youtu.be/" in query:
        return query.split("youtu.be/")[-1].split("?")[0]
    return None


async def _ytdlp_search_fallback(query: str, limit: int = 1) -> list:
    """
    Quota-free fallback used only when the entire YOUTUBE_API_KEYS pool is
    exhausted, or when no keys are configured at all. Uses yt-dlp's
    ytsearch: pseudo-URL instead of scraping YouTube's HTML directly.
    """
    def _run():
        ytdl_opts = {"quiet": True, "extract_flat": "in_playlist", "skip_download": True}
        with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            return info.get("entries") or []

    loop = asyncio.get_event_loop()
    entries = await loop.run_in_executor(None, _run)

    results = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id")
        results.append(
            {
                "id": vid,
                "title": e.get("title") or "Unknown",
                "duration_sec": int(e.get("duration") or 0),
                "duration_min": _seconds_to_min_str(e.get("duration") or 0),
                "thumbnail": (e.get("thumbnails") or [{}])[-1].get("url", "") if e.get("thumbnails") else
                             f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "link": f"https://www.youtube.com/watch?v={vid}",
            }
        )
    return results


async def _v3_search(query: str, limit: int = 1) -> list:
    """
    Search via YouTube Data API v3, with automatic key rotation and
    yt-dlp fallback if every key is exhausted or none are configured.
    Returns a normalized list of dicts: id, title, duration_sec,
    duration_min, thumbnail, link.
    """
    # A raw video ID/URL doesn't need a search call at all.
    direct_id = _extract_video_id_from_query(query)

    async with aiohttp.ClientSession() as session:
        if direct_id and len(direct_id) == 11:
            data = await _v3_get(
                session,
                "videos",
                {"part": "snippet,contentDetails", "id": direct_id},
            )
            if data and data.get("items"):
                item = data["items"][0]
                snippet = item["snippet"]
                secs = _iso8601_duration_to_seconds(item["contentDetails"]["duration"])
                return [
                    {
                        "id": item["id"],
                        "title": snippet["title"],
                        "duration_sec": secs,
                        "duration_min": _seconds_to_min_str(secs),
                        "thumbnail": snippet["thumbnails"]["high"]["url"].split("?")[0],
                        "link": f"https://www.youtube.com/watch?v={item['id']}",
                    }
                ]
            # fall through to fallback below

        else:
            search_data = await _v3_get(
                session,
                "search",
                {"part": "snippet", "q": query, "type": "video", "maxResults": limit},
            )
            if search_data and search_data.get("items"):
                ids = [it["id"]["videoId"] for it in search_data["items"] if it.get("id", {}).get("videoId")]
                if ids:
                    details_data = await _v3_get(
                        session,
                        "videos",
                        {"part": "snippet,contentDetails", "id": ",".join(ids)},
                    )
                    if details_data and details_data.get("items"):
                        results = []
                        for item in details_data["items"]:
                            snippet = item["snippet"]
                            secs = _iso8601_duration_to_seconds(item["contentDetails"]["duration"])
                            results.append(
                                {
                                    "id": item["id"],
                                    "title": snippet["title"],
                                    "duration_sec": secs,
                                    "duration_min": _seconds_to_min_str(secs),
                                    "thumbnail": snippet["thumbnails"]["high"]["url"].split("?")[0],
                                    "link": f"https://www.youtube.com/watch?v={item['id']}",
                                }
                            )
                        return results

    # Every key exhausted, none configured, or the API call failed outright.
    return await _ytdlp_search_fallback(query, limit=limit)


async def _ytdlp_search_multi_fallback(query: str, limit: int = 5) -> list:
    """
    Quota-free multi-result fallback for youtube_search_multi, used only
    when the YOUTUBE_API_KEYS pool is exhausted or none are configured.
    """
    def _run():
        ytdl_opts = {"quiet": True, "extract_flat": "in_playlist", "skip_download": True}
        with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            return info.get("entries") or []

    loop = asyncio.get_event_loop()
    entries = await loop.run_in_executor(None, _run)

    results = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id")
        if not vid:
            continue
        dur_sec = int(e.get("duration") or 0)
        thumb_list = e.get("thumbnails") or []
        thumb_url = (
            thumb_list[-1].get("url", "")
            if thumb_list else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        )
        results.append(
            {
                "id": vid,
                "title": e.get("title") or "Unknown",
                "duration": _seconds_to_min_str(dur_sec),
                "duration_sec": dur_sec,
                "channel": e.get("channel") or e.get("uploader") or "",
                "thumbnails": [{"url": thumb_url}] if thumb_url else [],
                "thumbnail": thumb_url,
                "link": f"https://www.youtube.com/watch?v={vid}",
            }
        )
    return results


async def youtube_search_multi(query: str, limit: int = 5) -> list:
    """
    Search YouTube and return up to `limit` normalized results, used by
    RishuMusic.utils.stream.autoplay for picking the next similar song.

    Each result dict has: id, title, duration (m:ss string), duration_sec,
    channel (string), thumbnails (list of {"url": ...}), thumbnail
    (string, same url), link. This shape matches what autoplay.py's
    get_best_song() and its fallback loop read via .get(...).

    Uses the same YOUTUBE_API_KEYS pool / key rotation as _v3_search, and
    falls back to a quota-free yt-dlp search if every key is exhausted or
    none are configured.
    """
    if not query:
        return []

    async with aiohttp.ClientSession() as session:
        search_data = await _v3_get(
            session,
            "search",
            {"part": "snippet", "q": query, "type": "video", "maxResults": limit},
        )
        if search_data and search_data.get("items"):
            ids = [
                it["id"]["videoId"]
                for it in search_data["items"]
                if it.get("id", {}).get("videoId")
            ]
            if ids:
                details_data = await _v3_get(
                    session,
                    "videos",
                    {"part": "snippet,contentDetails", "id": ",".join(ids)},
                )
                if details_data and details_data.get("items"):
                    results = []
                    for item in details_data["items"]:
                        snippet = item["snippet"]
                        secs = _iso8601_duration_to_seconds(
                            item["contentDetails"]["duration"]
                        )
                        thumbs = snippet.get("thumbnails", {}) or {}
                        thumb_url = (
                            thumbs.get("high", {}).get("url")
                            or thumbs.get("medium", {}).get("url")
                            or thumbs.get("default", {}).get("url", "")
                        )
                        if thumb_url:
                            thumb_url = thumb_url.split("?")[0]
                        results.append(
                            {
                                "id": item["id"],
                                "title": snippet.get("title", "Unknown"),
                                "duration": _seconds_to_min_str(secs),
                                "duration_sec": secs,
                                "channel": snippet.get("channelTitle", ""),
                                "thumbnails": [{"url": thumb_url}] if thumb_url else [],
                                "thumbnail": thumb_url,
                                "link": f"https://www.youtube.com/watch?v={item['id']}",
                            }
                        )
                    return results

    # Every key exhausted, none configured, or the API call failed outright.
    return await _ytdlp_search_multi_fallback(query, limit=limit)


_MIN_FILE_SIZE = 10000


def _valid_file(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > _MIN_FILE_SIZE


def _safe_remove(path: str):
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


async def _stream_to_file(
    session: aiohttp.ClientSession, url: str, file_path: str, timeout: int, **kwargs
) -> bool:
    """Streams `url` into file_path. Returns True only if the saved file
    looks valid (non-trivial size)."""
    async with session.get(
        url, timeout=aiohttp.ClientTimeout(total=timeout), **kwargs
    ) as resp:
        if resp.status != 200:
            return False
        with open(file_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(131072):
                f.write(chunk)
    return _valid_file(file_path)


def _find_url_in_json(data) -> Union[str, None]:
    """Looks for a download/stream URL in a JSON response from the worker."""
    if isinstance(data, dict):
        for key in ("url", "download_url", "stream_url", "link", "audio_url", "video_url"):
            val = data.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
        for val in data.values():
            found = _find_url_in_json(val)
            if found:
                return found
    elif isinstance(data, list):
        for val in data:
            found = _find_url_in_json(val)
            if found:
                return found
    return None


async def _download_via_worker(video_id: str, file_path: str, kind: str, timeout: int) -> bool:
    """Fallback download through the Cloudflare Worker. The worker may either
    stream the media directly, or return JSON containing a direct URL — both
    are handled."""
    if not WORKER_FALLBACK_API_URL:
        return False
    url = WORKER_FALLBACK_API_URL + WORKER_FALLBACK_PATH.format(video_id=video_id)
    params = {
        "id": video_id,
        "key": WORKER_FALLBACK_API_KEY,
        "type": kind,
        "quality": "480" if kind == "video" else "128",
    }
    headers = {"x-api-key": WORKER_FALLBACK_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    return False
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "json" in ctype:
                    data = await resp.json(content_type=None)
                    direct = _find_url_in_json(data)
                    if not direct:
                        return False
                else:
                    direct = None
                    with open(file_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(131072):
                            f.write(chunk)
            if direct:
                return await _stream_to_file(session, direct, file_path, timeout)
            return _valid_file(file_path)
    except Exception:
        return False


async def _fetch_media(video_id: str, file_path: str, kind: str, timeout: int) -> bool:
    """Primary MEOW API first, then the worker fallback."""
    quality = "480" if kind == "video" else "128"
    stream_url = f"{API_URL}/stream/{video_id}?key={API_KEY}&type={kind}&quality={quality}"
    try:
        async with aiohttp.ClientSession() as session:
            if await _stream_to_file(session, stream_url, file_path, timeout):
                return True
    except Exception:
        pass
    _safe_remove(file_path)

    if await _download_via_worker(video_id, file_path, kind, timeout):
        return True
    _safe_remove(file_path)
    return False


async def download_song(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
        return file_path

    # Cache hit — this song was played before, pull it from the cache
    # channel instead of hitting the source API again.
    cached_file_id = await _get_cached_entry(video_id, "audio")
    if cached_file_id:
        try:
            await app.download_media(cached_file_id, file_name=file_path)
            if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                return file_path
        except Exception:
            pass  # fall through to a normal download below

    if await _fetch_media(video_id, file_path, "audio", 300):
        queue_for_caching(video_id, file_path, "audio")
        return file_path
    return None


async def download_video(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
        return file_path

    cached_file_id = await _get_cached_entry(video_id, "video")
    if cached_file_id:
        try:
            await app.download_media(cached_file_id, file_name=file_path)
            if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                return file_path
        except Exception:
            pass

    if await _fetch_media(video_id, file_path, "video", 600):
        queue_for_caching(video_id, file_path, "video")
        return file_path
    return None


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        return bool(re.search(self.regex, link))

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        for message in messages:
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        return text[entity.offset: entity.offset + entity.length]
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = await _v3_search(link, limit=1)
        if not results:
            return None
        r = results[0]
        return r["title"], r["duration_min"], r["duration_sec"], r["thumbnail"], r["id"]

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = await _v3_search(link, limit=1)
        return results[0]["title"] if results else None

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = await _v3_search(link, limit=1)
        return results[0]["duration_min"] if results else None

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = await _v3_search(link, limit=1)
        return results[0]["thumbnail"] if results else None

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            downloaded_file = await download_video(link)
            if downloaded_file:
                return 1, downloaded_file
            return 0, "Video download failed"
        except Exception as e:
            return 0, f"Video download error: {e}"

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            plist = await Playlist.get(link)
        except Exception:
            return []
        videos = plist.get("videos") or []
        ids = []
        for data in videos[:limit]:
            if not data:
                continue
            vid = data.get("id")
            if not vid:
                continue
            ids.append(vid)
        return ids

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = await _v3_search(link, limit=1)
        if not results:
            return None
        r = results[0]
        track_details = {
            "title": r["title"],
            "link": r["link"],
            "vidid": r["id"],
            "duration_min": r["duration_min"],
            "thumb": r["thumbnail"],
        }
        return track_details, r["id"]

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        ytdl_opts = {"quiet": True}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    if "dash" not in str(format["format"]).lower():
                        formats_available.append(
                            {
                                "format": format["format"],
                                "filesize": format.get("filesize"),
                                "format_id": format["format_id"],
                                "ext": format["ext"],
                                "format_note": format["format_note"],
                                "yturl": link,
                            }
                        )
                except Exception:
                    continue
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = await _v3_search(link, limit=10)
        if not results or query_type >= len(results):
            return None
        r = results[query_type]
        return r["title"], r["duration_min"], r["thumbnail"], r["id"]

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            link = self.base + link
        try:
            if video:
                downloaded_file = await download_video(link)
            else:
                downloaded_file = await download_song(link)
            if downloaded_file:
                return downloaded_file, True
            return None, False
        except Exception:
            return None, False


YouTube = YouTubeAPI()
