from urllib.parse import unquote, urlsplit


_SAFE_SCHEMES = {"http", "https"}
_SUSPICIOUS_TOKENS = (
    "$(",
    "${",
    "`",
    "|",
    ";",
    "<",
    ">",
    "\n",
    "\r",
    "\t",
)
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}
_SPOTIFY_HOSTS = {"open.spotify.com"}
_APPLE_HOSTS = {"music.apple.com"}
_SOUNDCLOUD_HOSTS = {"soundcloud.com", "on.soundcloud.com"}
_RESSO_HOSTS = {"www.resso.com", "resso.com", "m.resso.com"}


def _decode_layers(value: str, rounds: int = 3) -> str:
    result = value or ""
    for _ in range(rounds):
        updated = unquote(result)
        if updated == result:
            break
        result = updated
    return result


def _contains_suspicious_text(value: str) -> bool:
    lowered = _decode_layers(value).lower()
    return any(token in lowered for token in _SUSPICIOUS_TOKENS)


def is_safe_media_url(url: str) -> bool:
    if not isinstance(url, str):
        return False

    url = url.strip()
    if not url or len(url) > 4096:
        return False
    if any(char.isspace() for char in url):
        return False
    if _contains_suspicious_text(url):
        return False

    parsed = urlsplit(url)
    if parsed.scheme.lower() not in _SAFE_SCHEMES:
        return False

    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname.startswith("-") or ".." in hostname:
        return False
    if _contains_suspicious_text(hostname):
        return False
    if _contains_suspicious_text(parsed.path) or _contains_suspicious_text(parsed.query):
        return False

    if hostname in _YOUTUBE_HOSTS:
        if hostname.endswith("youtu.be"):
            return bool(parsed.path.strip("/"))
        return parsed.path in {"/watch", "/playlist"} or parsed.path.startswith(
            ("/shorts/", "/live/", "/embed/")
        )

    if hostname in _SPOTIFY_HOSTS:
        return parsed.path.startswith(("/track/", "/playlist/", "/album/", "/artist/"))

    if hostname in _APPLE_HOSTS:
        return parsed.path.startswith(("/in/", "/us/", "/gb/", "/"))

    if hostname in _SOUNDCLOUD_HOSTS:
        return len([part for part in parsed.path.split("/") if part]) >= 1

    if hostname in _RESSO_HOSTS:
        return parsed.path.startswith("/")

    return True
