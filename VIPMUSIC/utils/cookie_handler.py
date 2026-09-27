"""Cookie file management for yt-dlp downloads.

The bot never stores cookie contents in logs.  A cookie URL is optional and
must be configured by the owner through COOKIES_URL or /updatecookies.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

COOKIE_PATH = os.getenv("YTDL_COOKIES", "cookies/cookies.txt")
_ALLOWED_HOSTS = {"gist.github.com", "gist.githubusercontent.com", "pastebin.com", "batbin.me"}


def _valid_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in _ALLOWED_HOSTS


async def download_cookies(url: str | None) -> str:
    if not _valid_url(url):
        raise ValueError("Only HTTPS Gist, Pastebin, and Batbin URLs are allowed")
    destination = Path(COOKIE_PATH)
    destination.parent.mkdir(parents=True, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            data = await response.read()
    if not data or len(data) > 5 * 1024 * 1024:
        raise ValueError("Cookie response is empty or too large")
    destination.write_bytes(data)
    return str(destination)
