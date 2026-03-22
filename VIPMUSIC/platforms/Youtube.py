import asyncio
import os
import re
from typing import Union

import aiohttp
import yt_dlp
from pyrogram.types import Message

# REMOVED: youtubesearchpython (deprecated)
# ADDED: Direct yt-dlp search functionality

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

    # ========== FIXED: Replaced youtubesearchpython with yt-dlp search ==========
    
    async def _search_yt_dlp(self, query: str, limit: int = 1):
        """Search YouTube using yt-dlp instead of youtubesearchpython"""
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
        
        # FIXED: Use yt-dlp search instead of VideosSearch
        results = await self._search_yt_dlp(link, limit=1)
        
        if not results:
            return None, None, 0, None, None
            
        result = results[0]
        title = result.get("title", "Unknown")
        duration_str = result.get("duration", "0:00")
        thumbnail = result.get("thumbnail", "")
        vidid = result.get("id", "")
        
        # Parse duration
        if str(duration_str) == "None" or not duration_str:
            duration_sec = 0
            duration_min = "0:00"
        else:
            duration_min = duration_str
            duration_sec = int(time_to_seconds(duration_str))
            
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
            
        results = await self._search_yt_dlp(link, limit=1)
        if results:
            return results[0].get("title", "Unknown")
        return "Unknown"

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
            
        results = await self._search_yt_dlp(link, limit=1)
        if results:
            return results[0].get("duration", "0:00")
        return "0:00"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
            
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
            
        # FIXED: Updated yt-dlp command for 2025 version
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--no-check-certificates",  # ADDED
            "--no-warnings",            # ADDED
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
        if "&" in link:
            link = link.split("&")[0]
            
        # FIXED: Updated shell command
        playlist = await shell_cmd(
            f'yt-dlp --no-check-certificates --no-warnings -i --get-id --flat-playlist --playlist-end {limit} --skip-download "{link}"'
        )
        
        try:
            result = playlist.split("\n")
            for key in result:
                if key == "":
                    result.remove(key)
        except:
            result = []
        return result

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
            
        results = await self._search_yt_dlp(link, limit=1)
        
        if not results:
            return {}, None
            
        result = results[0]
        title = result.get("title", "Unknown")
        duration_min = result.get("duration", "0:00")
        vidid = result.get("id", "")
        yturl = f"https://www.youtube.com/watch?v={vidid}"
        thumbnail = result.get("thumbnail", "")
        
        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail.split("?")[0] if "?" in str(thumbnail) else thumbnail,
        }
        return track_details, vidid

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
            
        ytdl_opts = {
            "quiet": True,
            "no_warnings": True,
            "no_check_certificates": True,  # ADDED
        }
        
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    str(format["format"])
                except:
                    continue
                if not "dash" in str(format["format"]).lower():
                    try:
                        format["format"]
                        format["filesize"]
                        format["format_id"]
                        format["ext"]
                        format["format_note"]
                    except:
                        continue
                    formats_available.append(
                        {
                            "format": format["format"],
                            "filesize": format["filesize"],
                            "format_id": format["format_id"],
                            "ext": format["ext"],
                            "format_note": format["format_note"],
                            "yturl": link,
                        }
                    )
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
            
        # FIXED: Use yt-dlp for slider/search results
        results = await self._search_yt_dlp(link, limit=10)
        
        if not results or query_type >= len(results):
            return None, None, None, None
            
        result = results[query_type]
        title = result.get("title", "Unknown")
        duration_min = result.get("duration", "0:00")
        vidid = result.get("id", "")
        thumbnail = result.get("thumbnail", "")
        
        return title, duration_min, thumbnail.split("?")[0] if "?" in str(thumbnail) else thumbnail, vidid

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

        def audio_dl():
            ydl_optssx = {
                "format": "bestaudio/best",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                # ADDED: 2025 compatibility options
                "no_check_certificates": True,
                "prefer_insecure": True,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["web"],  # FIXED: Use web client
                    }
                }
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            info = x.extract_info(link, False)
            xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                return xyz
            x.download([link])
            return xyz

        def video_dl():
            ydl_optssx = {
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                # ADDED: 2025 compatibility
                "no_check_certificates": True,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["web"],
                    }
                }
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            info = x.extract_info(link, False)
            xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                return xyz
            x.download([link])
            return xyz

        def song_video_dl():
            formats = f"{format_id}+140"
            fpath = f"downloads/{title}"
            ydl_optssx = {
                "format": formats,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "merge_output_format": "mp4",
                # ADDED
                "no_check_certificates": True,
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])

        def song_audio_dl():
            fpath = f"downloads/{title}.%(ext)s"
            ydl_optssx = {
                "format": format_id,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                # ADDED
                "no_check_certificates": True,
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])

        if songvideo:
            await loop.run_in_executor(None, song_video_dl)
            fpath = f"downloads/{title}.mp4"
            return fpath
        elif songaudio:
            await loop.run_in_executor(None, song_audio_dl)
            fpath = f"downloads/{title}.mp3"
            return fpath
        elif video:
            if await is_on_off(config.YTDOWNLOADER):
                direct = True
                downloaded_file = await loop.run_in_executor(None, video_dl)
            else:
                proc = await asyncio.create_subprocess_exec(
                    "yt-dlp",
                    "--no-check-certificates",  # ADDED
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
                    downloaded_file = stdout.decode().split("\n")[0]
                    direct = None
                else:
                    return None, None
        else:
            direct = True
            downloaded_file = await loop.run_in_executor(None, audio_dl)
            
        return downloaded_file, direct


