"""Shared helper: origin URL with CI token auth when running on Actions."""

import os
import subprocess
from pathlib import Path


def authenticated_remote_url(repo_root: Path) -> str:
    """Origin URL, with x-access-token auth injected on GitHub Actions.

    Local runs return the plain URL (git credential helper handles auth);
    runner pushes from temp clones need the token inline because checkout's
    extraheader config does not propagate to fresh repos.
    """
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.strip()
    token = os.environ.get("GITHUB_TOKEN", "")
    if token and url.startswith("https://github.com/"):
        return url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
    return url
