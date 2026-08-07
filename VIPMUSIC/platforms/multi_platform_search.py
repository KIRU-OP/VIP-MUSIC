"""
multi_platform_search.py

Adds JioSaavn / SoundCloud / Spotify search on top of the existing
YouTube-only pipeline in Youtube.py. Drop this next to Youtube.py
(e.g. VIPMUSIC/platforms/multi_platform_search.py) and import
`play_song()` from wherever the bot currently calls YouTube.track() /
YouTube.download() for a text query (e.g. the /play command handler).

IMPORTANT — read before wiring this in:

1. Spotify's official Web API does NOT hand out full-track audio to
   third-party apps. That's an intentional restriction in their
   developer terms, not a technical gap. So SpotifyAPI here only
   returns metadata (title/artist/duration/cover); play_song() then
   re-searches that metadata on JioSaavn/SoundCloud/YouTube to get an
   actual playable file. There is no way to legitimately stream full
   Spotify tracks through this API — any code claiming to do that is
   lying about what it's doing.

2. JioSaavn has no official public developer API. This uses the
   community-run saavn.dev proxy (unofficial, can change/break/vanish
   without notice). If you want something you control, self-host it:
   https://github.com/sumitkolhe/jiosaavn-api

3. SoundCloud's official API (api-v2) needs a client_id from an
   approved app at https://developers.soundcloud.com. New app
   approvals have been effectively closed for most developers for
   years. Without your own SOUNDCLOUD_CLIENT_ID env var, SoundCloudAPI
   just returns no results — it does not scrape/guess a client_id.

Set these env vars for whichever platforms you actually have access to:
    SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
    SOUNDCLOUD_CLIENT_ID
    JIOSAAVN_API_BASE   (defaults to https://saavn.dev/api)
Any platform whose credentials are missing is simply skipped.
"""

import asyncio
import base64
import os
import time
from typing import Dict, List, Optional, Tuple

import aiofiles
import aiohttp

from VIPMUSIC.platforms.Youtube import YouTube, _get_yt_session
from VIPMUSIC import LOGGER

logger = LOGGER(__name__)

# ============ CONFIG ============
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "22b6125bfe224587b722d6815002db2b")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "c9c63c6fbf2f467c8bc68624851e9773")
SOUNDCLOUD_CLIENT_ID = os.environ.get("SOUNDCLOUD_CLIENT_ID", "")
JIOSAAVN_API_BASE = os.environ.get("JIOSAAVN_API_BASE", "https://saavn.dev/api")

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def _safe_filename(text: str, max_len: int = 60) -> str:
    return "".join(c for c in text if c.isalnum() or c in " -_").strip()[:max_len] or "track"


async def _save_stream(url: str, file_path: str, extra_params: Optional[Dict] = None) -> Optional[str]:
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path
    try:
        session = await _get_yt_session()
        async with session.get(
            url, params=extra_params, timeout=aiohttp.ClientTimeout(total=120)
        ) as resp:
            if resp.status != 200:
                return None
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1 << 20):
                    await f.write(chunk)
        return file_path if os.path.exists(file_path) and os.path.getsize(file_path) > 0 else None
    except Exception as e:
        logger.warning(f"stream save failed: {e}")
        return None


# ============ SPOTIFY (official Web API — metadata only, see module docstring) ============
class SpotifyAPI:
    def __init__(self):
        self._token = None
        self._token_expiry = 0
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)

    async def _get_token(self, session: aiohttp.ClientSession) -> Optional[str]:
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        if not self.configured:
            return None
        async with self._lock:
            if self._token and time.time() < self._token_expiry - 30:
                return self._token
            auth = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
            try:
                async with session.post(
                    "https://accounts.spotify.com/api/token",
                    data={"grant_type": "client_credentials"},
                    headers={"Authorization": f"Basic {auth}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
            except Exception:
                return None
            self._token = data.get("access_token")
            self._token_expiry = time.time() + data.get("expires_in", 3600)
            return self._token

    async def search(self, query: str, limit: int = 3) -> List[Dict]:
        if not self.configured:
            return []
        session = await _get_yt_session()
        token = await self._get_token(session)
        if not token:
            return []
        try:
            async with session.get(
                "https://api.spotify.com/v1/search",
                params={"q": query, "type": "track", "limit": limit},
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception:
            return []

        out = []
        for t in data.get("tracks", {}).get("items", []):
            artists = ", ".join(a["name"] for a in t.get("artists", []))
            images = t.get("album", {}).get("images", [])
            out.append({
                "platform": "spotify",
                "title": t.get("name", ""),
                "artist": artists,
                "duration_ms": t.get("duration_ms"),
                "thumb": images[0]["url"] if images else "",
                "url": t.get("external_urls", {}).get("spotify", ""),
                "search_query": f"{t.get('name', '')} {artists}".strip(),
            })
        return out


# ============ JIOSAAVN (unofficial saavn.dev proxy — direct stream url) ============
class JioSaavnAPI:
    async def search(self, query: str, limit: int = 3) -> List[Dict]:
        session = await _get_yt_session()
        try:
            async with session.get(
                f"{JIOSAAVN_API_BASE}/search/songs",
                params={"query": query, "limit": limit},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception:
            return []

        results = (data.get("data") or {}).get("results", [])
        out = []
        for s in results:
            download_urls = s.get("downloadUrl") or []
            best = download_urls[-1]["url"] if download_urls else None  # last entry = highest quality
            out.append({
                "platform": "jiosaavn",
                "id": s.get("id", ""),
                "title": s.get("name", ""),
                "artist": ", ".join(a.get("name", "") for a in (s.get("artists", {}).get("primary") or [])),
                "duration_sec": s.get("duration"),
                "thumb": (s.get("image") or [{}])[-1].get("url", ""),
                "url": s.get("url", ""),
                "stream_url": best,
            })
        return out

    async def download(self, track: Dict) -> Optional[str]:
        if not track.get("stream_url"):
            return None
        file_path = os.path.join(DOWNLOAD_DIR, f"saavn_{track.get('id') or _safe_filename(track['title'])}.mp3")
        return await _save_stream(track["stream_url"], file_path)


# ============ SOUNDCLOUD (official API v2 — needs your own client_id) ============
class SoundCloudAPI:
    @property
    def configured(self) -> bool:
        return bool(SOUNDCLOUD_CLIENT_ID)

    async def search(self, query: str, limit: int = 3) -> List[Dict]:
        if not self.configured:
            return []
        session = await _get_yt_session()
        try:
            async with session.get(
                "https://api-v2.soundcloud.com/search/tracks",
                params={"q": query, "client_id": SOUNDCLOUD_CLIENT_ID, "limit": limit},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception:
            return []

        out = []
        for t in data.get("collection", []):
            transcodings = (t.get("media") or {}).get("transcodings", [])
            progressive = next(
                (tr for tr in transcodings if tr.get("format", {}).get("protocol") == "progressive"), None
            )
            out.append({
                "platform": "soundcloud",
                "title": t.get("title", ""),
                "artist": (t.get("user") or {}).get("username", ""),
                "duration_sec": (t.get("duration") or 0) // 1000,
                "thumb": t.get("artwork_url", ""),
                "url": t.get("permalink_url", ""),
                "_transcoding_url": progressive["url"] if progressive else None,
            })
        return out

    async def _resolve_stream_url(self, transcoding_url: str) -> Optional[str]:
        session = await _get_yt_session()
        try:
            async with session.get(
                transcoding_url,
                params={"client_id": SOUNDCLOUD_CLIENT_ID},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("url")
        except Exception:
            return None

    async def download(self, track: Dict) -> Optional[str]:
        transcoding_url = track.get("_transcoding_url")
        if not transcoding_url:
            return None
        stream_url = await self._resolve_stream_url(transcoding_url)
        if not stream_url:
            return None
        file_path = os.path.join(DOWNLOAD_DIR, f"sc_{_safe_filename(track.get('title', 'track'))}.mp3")
        return await _save_stream(stream_url, file_path)


spotify = SpotifyAPI()
jiosaavn = JioSaavnAPI()
soundcloud = SoundCloudAPI()

# Order platforms are tried in play_song(). Reorder if you'd rather
# prefer, say, SoundCloud over JioSaavn.
PLATFORM_PRIORITY = ["jiosaavn", "soundcloud", "spotify", "youtube"]


async def search_all_platforms(query: str) -> Dict[str, List[Dict]]:
    """Search every configured platform concurrently. Missing credentials -> empty list, no error."""
    names = ["jiosaavn", "soundcloud", "spotify"]
    coros = [jiosaavn.search(query), soundcloud.search(query), spotify.search(query)]
    results = await asyncio.gather(*coros, return_exceptions=True)
    return {name: (res if isinstance(res, list) else []) for name, res in zip(names, results)}


async def play_song(query: str) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Search JioSaavn, SoundCloud, and Spotify (metadata) concurrently,
    then try to produce a playable local file in PLATFORM_PRIORITY
    order, falling back to plain YouTube search+download last (same
    behaviour the bot already had).

    Returns (local_file_path, track_info) or (None, None) if nothing
    playable was found anywhere.
    """
    results = await search_all_platforms(query)

    # 1. JioSaavn — already gives a direct stream url
    for track in results.get("jiosaavn", []):
        path = await jiosaavn.download(track)
        if path:
            return path, track

    # 2. SoundCloud — one extra resolve step for the stream url
    for track in results.get("soundcloud", []):
        path = await soundcloud.download(track)
        if path:
            return path, track

    # 3. Spotify — metadata only; resolve the actual audio via YouTube
    for track in results.get("spotify", []):
        yt_query = track.get("search_query") or f"{track.get('title')} {track.get('artist')}"
        try:
            info, _vid = await YouTube.track(yt_query)
            path, _ = await YouTube.download(info["link"])
            if path:
                track["resolved_via"] = "youtube"
                return path, track
        except Exception:
            continue

    # 4. Plain YouTube — original fallback behaviour, unchanged
    try:
        info, _vid = await YouTube.track(query)
        path, _ = await YouTube.download(info["link"])
        if path:
            return path, {"platform": "youtube", "title": info.get("title"), "url": info.get("link")}
    except Exception:
        pass

    return None, None
