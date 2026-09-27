import os
import asyncio
import functools
import yt_dlp

from VIPMUSIC.utils.cookie_handler import COOKIE_PATH

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def _cookie_opts() -> dict:
    opts = {}
    try:
        if COOKIE_PATH and os.path.exists(COOKIE_PATH) and os.path.getsize(COOKIE_PATH) > 0:
            opts["cookiefile"] = COOKIE_PATH
    except Exception:
        pass
    return opts


def _video_id(link: str) -> str:
    return link.split("v=")[-1].split("&")[0] if "v=" in link else link


def _sync_download(link: str, type: str = "audio") -> str:
    video_id = _video_id(link)
    if not video_id or len(video_id) < 3:
        return None

    ext = "mp4" if type == "video" else "webm"
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 10240:
        return file_path

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "geo_bypass": True,
        "force_ipv4": True,
        "outtmpl": file_path,
        "format": (
            "best[height<=?720][width<=?1280]/best"
            if type == "video"
            else "bestaudio[ext=webm]/bestaudio/best"
        ),
    }
    ydl_opts.update(_cookie_opts())

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])
    except Exception:
        return None

    if os.path.exists(file_path) and os.path.getsize(file_path) > 10240:
        return file_path
    return None


async def yt_dlp_download(link: str, type: str = "audio") -> str:
    loop = asyncio.get_event_loop()
    func = functools.partial(_sync_download, link, type)
    return await loop.run_in_executor(None, func)


async def download_audio_concurrent(link: str) -> str:
    return await yt_dlp_download(link, type="audio")
