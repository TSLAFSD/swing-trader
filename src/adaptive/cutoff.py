"""Lever 3 — adaptive acceptance cutoff (semi-auto, AUTO).

Adapts the EXISTING send-stage strength cutoff (settings.MIN_STRENGTH_SEND)
rather than adding a parallel one. Every weekly run it compares the realized
+10d hit-rate of the marginal ACCEPTED band (strength just above the cutoff)
and the marginal REJECTED band (just below) — all signals are logged BEFORE the
send filter, so there is no censoring. The cutoff is nudged at most
ACCEPTANCE_CUTOFF_MAX_STEP per run, clamped to [FLOOR, CEILING]:

  - raise when the just-accepted band loses money (suppress weak signals), and
  - lower (carefully) only when the just-rejected band clearly outperforms, so
    the bar cannot ratchet permanently to the ceiling and censor good signals.

Read-only on price. Below ACCEPTANCE_MIN_SAMPLE it does nothing (neutral). When
ADAPTIVE_LOOP_ENABLED/ACCEPTANCE_CUTOFF_ENABLED is off, effective_cutoff()
returns MIN_STRENGTH_SEND, so the system behaves exactly like the baseline.
"""

import json
import logging
from datetime import date

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

STATE_FILE = settings.DATA_ROOT / "state" / "acceptance_cutoff.json"
BAND = 10.0  # strength band width around the cutoff for marginal analysis


def _load(path):
    path = path or STATE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save(cutoff: float, path) -> None:
    path = path or STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cutoff": cutoff, "updated": str(date.today())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def effective_cutoff(path=None) -> float:
    """The strength cutoff send_filter should apply (baseline when adaptive off)."""
    if not (settings.ADAPTIVE_LOOP_ENABLED and settings.ACCEPTANCE_CUTOFF_ENABLED):
        return settings.MIN_STRENGTH_SEND
    state = _load(path)
    if not state or "cutoff" not in state:
        return settings.MIN_STRENGTH_SEND
    return float(state["cutoff"])


def _band(fwd: pd.DataFrame, lo: float, hi: float) -> tuple[int, float, float]:
    """(n, +10d hit-rate, mean +10d) for signals with strength in [lo, hi)."""
    if fwd is None or fwd.empty or "strength" not in fwd.columns or "fwd_10d" not in fwd.columns:
        return 0, float("nan"), float("nan")
    band = fwd[(fwd["strength"] >= lo) & (fwd["strength"] < hi)]
    realized = pd.to_numeric(band["fwd_10d"], errors="coerce").dropna()
    if realized.empty:
        return 0, float("nan"), float("nan")
    return len(realized), float((realized > 0).mean()), float(realized.mean())


def propose_and_apply(fwd: pd.DataFrame, path=None) -> dict | None:
    """Weekly: nudge the cutoff from marginal-band realized performance.

    Returns {old, new, changed, reason_kr} (the change is persisted only when
    changed), or None when the lever is disabled.
    """
    if not (settings.ADAPTIVE_LOOP_ENABLED and settings.ACCEPTANCE_CUTOFF_ENABLED):
        return None
    current = effective_cutoff(path)
    step = settings.ACCEPTANCE_CUTOFF_MAX_STEP
    floor, ceiling = settings.ACCEPTANCE_CUTOFF_FLOOR, settings.ACCEPTANCE_CUTOFF_CEILING
    min_n = settings.ACCEPTANCE_MIN_SAMPLE

    n_acc, hit_acc, mean_acc = _band(fwd, current, current + BAND)
    n_rej, hit_rej, mean_rej = _band(fwd, max(current - BAND, 0.0), current)

    new, reason = current, "표본 부족 — 미적용"
    if n_acc >= min_n and mean_acc < 0 and hit_acc < 0.5:
        new = min(current + step, ceiling)
        reason = (
            f"수용 경계({current:.0f}~{current + BAND:.0f}) 적중 {hit_acc * 100:.0f}%·"
            f"평균 {mean_acc * 100:+.1f}% → 컷오프 상향"
        )
    elif n_rej >= min_n and mean_rej > 0 and hit_rej >= 0.55 and current > floor:
        new = max(current - step, floor)
        reason = (
            f"기각 경계({max(current - BAND, 0):.0f}~{current:.0f}) 적중 {hit_rej * 100:.0f}%·"
            f"평균 {mean_rej * 100:+.1f}% → 컷오프 하향"
        )
    new = round(max(floor, min(ceiling, new)), 1)
    changed = new != round(current, 1)
    if changed:
        _save(new, path)
        logger.info("acceptance cutoff %.1f -> %.1f (%s)", current, new, reason)
    return {"old": round(current, 1), "new": new, "changed": changed, "reason_kr": reason}
