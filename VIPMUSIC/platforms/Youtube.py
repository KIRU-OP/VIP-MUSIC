import os
import re
import yt_dlp
import random
import asyncio
from pathlib import Path

from py_yt import Playlist, VideosSearch
from VIPMUSIC import logger
from VIPMUSIC.helpers import Track, utils

class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookie_dir = "VIPMUSIC/cookies"
        self.download_dir = "downloads"
        self.cookies = []
        self.checked = False
        
        # Ensure required directories exist
        os.makedirs(self.cookie_dir, exist_ok=True)
        os.makedirs(self.download_dir, exist_ok=True)

        # Robust YouTube URL Validation
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )

    def get_cookies(self):
        """Loads random cookie file from the local cookie directory if available."""
        if not self.checked:
            if os.path.exists(self.cookie_dir):
                for file in os.listdir(self.cookie_dir):
                    if file.endswith(".txt"):
                        self.cookies.append(os.path.join(self.cookie_dir, file))
            self.checked = True
            
        if not self.cookies:
            return None
        return random.choice(self.cookies)

    def valid(self, url: str) -> bool:
        """Validates if a URL is a proper YouTube link."""
        return bool(re.match(self.regex, url))

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        """Searches for a single track on YouTube."""
        try:
            _search = VideosSearch(query, limit=1, with_live=False)
            results = await _search.next()
            
            if results and results.get("result"):
                data = results["result"][0]
                return Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    message_id=m_id,
                    title=data.get("title")[:50], 
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    video=video,
                )
        except Exception as e:
            logger.error(f"Search Error: {e}")
        return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track]:
        """Fetches tracks from a YouTube playlist."""
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist.get("videos", [])[:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=data.get("title")[:50],
                    thumbnail=data.get("thumbnails")[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception as e:
            logger.error(f"Playlist Error: {e}")
        return tracks

    async def download(self, video_id: str, video: bool = False) -> str | None:
        """Downloads the video/audio using yt-dlp."""
        url = self.base + video_id
        ext = "mp4" if video else "webm"
        filename = os.path.join(self.download_dir, f"{video_id}.{ext}")

        # Return file if already downloaded
        if os.path.exists(filename):
            return filename

        cookie = self.get_cookies()
        
        # Standard Professional yt-dlp Options
        ydl_opts = {
            "outtmpl": os.path.join(self.download_dir, "%(id)s.%(ext)s"),
            "quiet": True,
            "noplaylist": True,
            "geo_bypass": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "cookiefile": cookie,
        }

        if video:
            ydl_opts.update({
                "format": "bestvideo[height<=720]+bestaudio/best[height<=720]",
                "merge_output_format": "mp4",
            })
        else:
            ydl_opts.update({
                "format": "bestaudio[ext=webm]/bestaudio/best",
            })

        def _download():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                return filename
            except Exception as ex:
                logger.error(f"Download failed for {video_id}: {ex}")
                return None

        # Running synchronous download in a thread to keep the loop non-blocking
        return await asyncio.to_thread(_download)
