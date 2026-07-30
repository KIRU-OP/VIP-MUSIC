import os

# Path to the cookies.txt file used by yt-dlp for authenticated/age-restricted
# or region-locked YouTube downloads.
#
# If this file does not exist (or is empty), Youtube.py's _cookiefile_path()
# will simply skip passing --cookies to yt-dlp, so this is safe even if you
# don't have a cookies.txt file yet.

COOKIE_DIR = os.path.join(os.getcwd(), "cookies")
COOKIE_PATH = os.path.join(COOKIE_DIR, "cookies.txt")

os.makedirs(COOKIE_DIR, exist_ok=True)
