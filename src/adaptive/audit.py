"""Adaptive-loop audit trail — every applied change, append-only.

Stored as data/state/adaptive_audit.json (a JSON array — NOT .jsonl, because
the data-branch publish/restore glob is *.parquet/*.json and .jsonl would not
ride along). Each entry records what changed and the numbers that triggered it,
so an applied auto/approved change is always reconstructable.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from config import settings

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
AUDIT_FILE = settings.DATA_ROOT / "state" / "adaptive_audit.json"


def load(path=None) -> list[dict]:
    """Load the audit log (empty list when missing/unreadable)."""
    path = path or AUDIT_FILE
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")) or []
    except (json.JSONDecodeError, OSError):
        logger.warning("adaptive audit: %s unreadable", path, exc_info=True)
        return []


def record(lever: str, old, new, trigger: str, *, regime: str | None = None, path=None) -> None:
    """Append one applied-change entry to the audit log."""
    path = path or AUDIT_FILE
    log = load(path)
    log.append(
        {
            "ts": datetime.now(KST).isoformat(timespec="seconds"),
            "lever": lever,
            "old": old,
            "new": new,
            "trigger": trigger,
            "regime": regime,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("adaptive audit: %s %s -> %s", lever, old, new)
