"""Publish generated reports to the gh-pages branch (GitHub Pages).

Same single-squashed-commit convention as the data branch: ALL report files
are retained (old URLs keep working) but branch history is rewritten each
publish to avoid repo bloat. A .nojekyll file disables Jekyll processing and
no index.html ever exists (non-guessable URLs only).
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from config import settings
from src.report.html_builder import REPORTS_OUT_DIR

logger = logging.getLogger(__name__)


def publish_reports(out_dir: Path | None = None) -> int:
    """Merge new reports with the existing branch contents and force-push.

    Args:
        out_dir: Directory of freshly generated reports.

    Returns:
        Number of report files now on the branch (0 = nothing to publish).
    """
    out_dir = out_dir or REPORTS_OUT_DIR
    new_files = list(out_dir.glob("*.html")) if out_dir.exists() else []
    from src.data.git_remote import authenticated_remote_url

    repo_root = settings.REPO_ROOT
    branch = settings.REPORTS_BRANCH
    remote_url = authenticated_remote_url(repo_root)

    with tempfile.TemporaryDirectory(prefix="pages-") as tmp:
        tmp_path = Path(tmp)

        def git(*args: str, cwd: Path = tmp_path) -> subprocess.CompletedProcess:
            return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)

        # Pull existing reports so old URLs keep working.
        clone = git("clone", "--depth", "1", "--branch", branch, remote_url, str(tmp_path / "old"), cwd=repo_root)
        existing_dir = tmp_path / "old"
        site = tmp_path / "site"
        site.mkdir()
        if clone.returncode == 0:
            for f in existing_dir.glob("*.html"):
                shutil.copy2(f, site / f.name)
        for f in new_files:
            shutil.copy2(f, site / f.name)
        total = len(list(site.glob("*.html")))
        if total == 0:
            logger.info("publisher: no reports to publish")
            return 0
        (site / ".nojekyll").touch()

        def gits(*args: str) -> None:
            subprocess.run(["git", *args], cwd=site, check=True, capture_output=True)

        gits("init", "--initial-branch", branch)
        gits("config", "user.email", "pipeline@swing-trader")
        gits("config", "user.name", "swing-trader pipeline")
        gits("add", "-A")
        gits("commit", "-m", "reports snapshot (squashed)")
        gits("remote", "add", "origin", remote_url)
        gits("push", "--force", "origin", branch)
    logger.info("publisher: %d reports live on %s", total, branch)
    return total
