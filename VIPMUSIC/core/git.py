import asyncio
import shlex
from typing import Tuple
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError
import config
from ..logging import LOGGER

# --- Loop Error Fix ---
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

def install_req(cmd: str) -> Tuple[str, str, int, int]:
    async def install_requirements():
        args = shlex.split(cmd)
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return (
            stdout.decode("utf-8", "replace").strip(),
            stderr.decode("utf-8", "replace").strip(),
            process.returncode,
            process.pid,
        )
    return loop.run_until_complete(install_requirements())

def git():
    REPO_LINK = config.UPSTREAM_REPO
    if config.GIT_TOKEN:
        GIT_USERNAME = REPO_LINK.split("com/")[1].split("/")[0]
        TEMP_REPO = REPO_LINK.split("https://")[1]
        UPSTREAM_REPO = f"https://{GIT_USERNAME}:{config.GIT_TOKEN}@{TEMP_REPO}"
    else:
        UPSTREAM_REPO = config.UPSTREAM_REPO

    try:
        repo = Repo()
        LOGGER(__name__).info(f"Git Client Found.")
    except (InvalidGitRepositoryError, GitCommandError):
        repo = Repo.init()
        if "origin" in repo.remotes:
            origin = repo.remote("origin")
        else:
            origin = repo.create_remote("origin", UPSTREAM_REPO)
        origin.fetch()
        
        # ऑटोमैटिक ब्रांच डिटेक्शन
        try:
            BRANCH = config.UPSTREAM_BRANCH
            repo.create_head(BRANCH, origin.refs[BRANCH])
        except:
            # अगर config वाली ब्रांच नहीं मिली, तो जो भी पहली ब्रांच मिले उसे पकड़ लो
            BRANCH = origin.refs[0].remote_head
            repo.create_head(BRANCH, origin.refs[BRANCH])
            
        repo.heads[BRANCH].set_tracking_branch(origin.refs[BRANCH])
        repo.heads[BRANCH].checkout(True)

    try:
        nrs = repo.remote("origin")
    except:
        nrs = repo.create_remote("origin", UPSTREAM_REPO)

    try:
        # यहाँ हम चेक कर रहे हैं कि रिमोट पर कौन सी ब्रांच है
        nrs.fetch()
        active_branch = repo.active_branch.name
        nrs.pull(active_branch)
        LOGGER(__name__).info(f"Successfully updated from branch: {active_branch}")
    except Exception as e:
        LOGGER(__name__).error(f"Update skipped due to: {e}")

    install_req("pip3 install --no-cache-dir -r requirements.txt")
