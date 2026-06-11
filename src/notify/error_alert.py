"""Workflow failure handler: send the copy-pasteable Korean error alert.

Usage (Actions `if: failure()` step):
    python -m src.notify.error_alert "한국 정규 스캔" run.log
Covers failures OUTSIDE main.py's own crash guard (pip install, OOM, etc.).
"""

import sys
from pathlib import Path

from src.notify.messages import error_alert
from src.notify.telegram import send_message


def main() -> None:
    """Read the job log tail and alert the owner."""
    job_kr = sys.argv[1] if len(sys.argv) > 1 else "작업"
    log_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    tail = ""
    if log_path and log_path.exists():
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    if not tail:
        tail = "(로그 파일 없음 — Actions 웹 로그를 확인하세요)"
    send_message(error_alert(job_kr, tail))


if __name__ == "__main__":
    main()
