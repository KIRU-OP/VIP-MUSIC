import asyncio
import os
import re
from typing import Union

import aiohttp
import yt_dlp
from pyrogram.types import Message

import config
from VIPMUSIC.utils.database import is_on_off
from VIPMUSIC.utils.formatters import time_to_seconds


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
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    def _parse_duration(self, duration):
        """Helper to convert various yt-dlp duration formats to MM:SS or HH:MM:SS"""
        if duration is None:
            return "0:00"
        
        try:
            # If duration is a string like "197.0" or an int 197
            seconds = int(float(duration))
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            if h > 0:
                return f"{h}:{m:02d}:{s:02d}"
            else:
                return f"{m}:{s:02d}"
        except (ValueError, TypeError):
            # If it's already a string like "03:17", return as is
            return str(duration)

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if re.search(self.regex, link):
            return True
        else:
            return False

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == "url":
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == "text_link":
                        return entity.url
        if offset in (None,):
            return None
        return text[offset : offset + length]

    async def _search_yt_dlp(self, query: str, limit: int = 1):
        search_query = f"ytsearch{limit}:{query}"
        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "force_generic_extractor": False,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                results = ydl.extract_info(search_query, download=False)
                if 'entries' in results:
                    return results['entries']
                return []
        except Exception as e:
            print(f"Search error: {e}")
            return []

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        
        results = await self._search_yt_dlp(link, limit=1)
        if not results:
            return None, None, 0, None, None
            
        result = results[0]
        title = result.get("title", "Unknown")
        
        # FIXED: Ensure duration is properly formatted before returning
        raw_duration = result.get("duration")
        duration_min = self._parse_duration(raw_duration)
        duration_sec = int(time_to_seconds(duration_min))
        
        thumbnail = result.get("thumbnail", "")
        vidid = result.get("id", "")
            
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        results = await self._search_yt_dlp(link, limit=1)
        return results[0].get("title", "Unknown") if results else "Unknown"

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        results = await self._search_yt_dlp(link, limit=1)
        if results:
            return self._parse_duration(results[0].get("duration"))
        return "0:00"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        results = await self._search_yt_dlp(link, limit=1)
        if results:
            thumb = results[0].get("thumbnail", "")
            return thumb.split("?")[0] if "?" in str(thumb) else thumb
        return ""

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
            
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--no-check-certificates",
            "--no-warnings",
            "-g",
            "-f",
            "best[height<=?720][width<=?1280]",
            f"{link}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stdout:
            return 1, stdout.decode().split("\n")[0]
        else:
            return 0, stderr.decode()

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        playlist = await shell_cmd(
            f'yt-dlp --no-check-certificates --no-warnings -i --get-id --flat-playlist --playlist-end {limit} --skip-download "{link}"'
        )
        try:
            result = [k for k in playlist.split("\n") if k]
        except:
            result = []
        return result

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        results = await self._search_yt_dlp(link, limit=1)
        if not results:
            return {}, None
            
        result = results[0]
        vidid = result.get("id", "")
        # FIXED: Formatting duration here
        duration_min = self._parse_duration(result.get("duration"))
        
        track_details = {
            "title": result.get("title", "Unknown"),
            "link": f"https://www.youtube.com/watch?v={vidid}",
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": result.get("thumbnail", ""),
        }
        return track_details, vidid

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        results = await self._search_yt_dlp(link, limit=10)
        if not results or query_type >= len(results):
            return None, None, None, None
            
        result = results[query_type]
        duration_min = self._parse_duration(result.get("duration"))
        thumbnail = result.get("thumbnail", "")
        
        return result.get("title", "Unknown"), duration_min, thumbnail, result.get("id", "")

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
        loop = asyncio.get_running_loop()

        common_opts = {
            "geo_bypass": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
            "no_check_certificates": True,
            "extractor_args": {"youtube": {"player_client": ["web"]}}
        }

        def audio_dl():
            opts = {**common_opts, "format": "bestaudio/best", "outtmpl": "downloads/%(id)s.%(ext)s"}
            with yt_dlp.YoutubeDL(opts) as x:
                info = x.extract_info(link, False)
                fpath = os.path.join("downloads", f"{info['id']}.{info['ext']}")
                if os.path.exists(fpath): return fpath
                x.download([link])
                return fpath

        def video_dl():
            opts = {**common_opts, "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])", "outtmpl": "downloads/%(id)s.%(ext)s"}
            with yt_dlp.YoutubeDL(opts) as x:
                info = x.extract_info(link, False)
                fpath = os.path.join("downloads", f"{info['id']}.{info['ext']}")
                if os.path.exists(fpath): return fpath
                x.download([link])
                return fpath

        if songvideo:
            await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL({**common_opts, "format": f"{format_id}+140", "outtmpl": f"downloads/{title}", "merge_output_format": "mp4"}).download([link]))
            return f"downloads/{title}.mp4"
        elif songaudio:
            await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL({**common_opts, "format": format_id, "outtmpl": f"downloads/{title}.%(ext)s", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]}).download([link]))
            return f"downloads/{title}.mp3"
        elif video:
            if await is_on_off(config.YTDOWNLOADER):
                return await loop.run_in_executor(None, video_dl), True
            else:
                proc = await asyncio.create_subprocess_exec("yt-dlp", "--no-check-certificates", "-g", "-f", "best[height<=?720]", link, stdout=asyncio.subprocess.PIPE)
                stdout, _ = await proc.communicate()
                return (stdout.decode().split("\n")[0], None) if stdout else (None, None)
        else:
            return await loop.run_in_executor(None, audio_dl), True
