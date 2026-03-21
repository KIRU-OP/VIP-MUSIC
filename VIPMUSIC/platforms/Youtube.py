from __future__ import annotations
import asyncio
import os
import random
import re
import logging
from typing import Union, List, Optional

from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch, Playlist
import yt_dlp

import config
from VIPMUSIC.utils.database import is_on_off
from VIPMUSIC.utils.formatters import time_to_seconds

# Initialize Logger
logger = logging.getLogger(__name__)

class Track:
    def __init__(self, id, channel_name, duration, duration_sec, title, thumbnail, url, video, message_id=None, view_count=None, user=None):
        self.id = id
        self.channel_name = channel_name
        self.duration = duration
        self.duration_sec = duration_sec
        self.title = title
        self.thumbnail = thumbnail
        self.url = url
        self.video = video
        self.message_id = message_id
        self.view_count = view_count
        self.user = user

class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookie_dir = "VIPMUSIC/cookies"
        self.download_dir = "downloads"
        self.cookies = []
        self.checked = False
        
        os.makedirs(self.cookie_dir, exist_ok=True)
        os.makedirs(self.download_dir, exist_ok=True)

        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )

    # --- ADDED THE MISSING URL METHOD ---
    async def url(self, message: Message) -> str | bool:
        """Extracts a YouTube URL from a message or a replied-to message."""
        messages = [message]
        if message.reply_to_message:
            messages.append(message.reply_to_message)

        for msg in messages:
            text = msg.text or msg.caption
            if not text:
                continue

            # Check if text is a direct URL match
            if re.match(self.regex, text):
                return text

            # Check message entities for links
            entities = msg.entities or msg.caption_entities
            if entities:
                for entity in entities:
                    if entity.type == MessageEntityType.URL:
                        url = text[entity.offset : entity.offset + entity.length]
                        if re.match(self.regex, url):
                            return url
                    elif entity.type == MessageEntityType.TEXT_LINK:
                        if re.match(self.regex, entity.url):
                            return entity.url
        return False

    def get_cookies(self):
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
        return bool(re.match(self.regex, url))

    async def search(self, query: str, m_id: int, video: bool = False) -> Optional[Track]:
        try:
            _search = VideosSearch(query, limit=1, with_live=False)
            results = await _search.next()
            
            if results and results.get("result"):
                data = results["result"][0]
                return Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"),
                    duration_sec=time_to_seconds(data.get("duration")), 
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

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> List[Track]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist.get("videos", [])[:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=time_to_seconds(data.get("duration")),
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

    async def download(self, video_id: str, video: bool = False) -> Optional[str]:
        url = self.base + video_id
        ext = "mp4" if video else "webm"
        filename = os.path.join(self.download_dir, f"{video_id}.{ext}")

        if os.path.exists(filename):
            return filename

        cookie = self.get_cookies()
        
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

        return await asyncio.to_thread(_download)
