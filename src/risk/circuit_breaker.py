"""Per-strategy circuit breaker (spec §5.3, Freqtrade 'protections' reimplemented).

If a strategy's trailing CB_TRAILING_SIGNALS signals have a mean realized
+10d forward return below CB_MEAN_FWD10_MIN, it is suspended (signals muted,
Telegram notice) until the weekly job re-evaluates. State persists as JSON
on the data branch.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

STATE_FILE = settings.DATA_ROOT / "state" / "circuit_breaker.json"


@dataclass
class BreakerDecision:
    """Outcome of evaluating one strategy's trailing performance."""

    strategy_id: str
    suspended: bool
    trailing_n: int
    mean_fwd10: float | None
    reason_kr: str


def load_state(path: Path | None = None) -> dict[str, dict]:
    """Load {strategy_id: {suspended, since, mean_fwd10}} (empty when absent)."""
    path = path or STATE_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, dict], path: Path | None = None) -> None:
    """Persist breaker state (rides the data branch)."""
    path = path or STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_suspended(strategy_id: str, state: dict[str, dict] | None = None) -> bool:
    """True when the strategy is currently suspended (scan-time check)."""
    state = state if state is not None else load_state()
    return bool(state.get(strategy_id, {}).get("suspended", False))


def evaluate(strategy_id: str, fwd: pd.DataFrame) -> BreakerDecision:
    """Evaluate the trailing-N realized performance for one strategy.

    Args:
        strategy_id: Strategy under evaluation.
        fwd: tracker.forward_returns() output (all strategies).

    Returns:
        BreakerDecision; insufficient realized data never suspends.
    """
    n_window = settings.CB_TRAILING_SIGNALS
    grp = (
        fwd[fwd["strategy_id"] == strategy_id]
        .sort_values("signal_date")
        .tail(n_window)
    )
    realized = grp["fwd_10d"].dropna()
    if len(realized) < n_window // 2:  # not enough realized outcomes yet
        return BreakerDecision(
            strategy_id=strategy_id, suspended=False, trailing_n=len(realized),
            mean_fwd10=None,
            reason_kr=f"실현 수익률 표본 부족 ({len(realized)}/{n_window}) — 판단 보류",
        )
    mean10 = float(realized.mean())
    suspended = mean10 < settings.CB_MEAN_FWD10_MIN
    reason = (
        f"최근 {len(realized)}건 시그널의 +10일 평균 수익률 {mean10 * 100:+.1f}% — "
        + (
            f"기준({settings.CB_MEAN_FWD10_MIN * 100:.0f}%) 미달, 전략 일시 중단"
            if suspended
            else "정상"
        )
    )
    return BreakerDecision(
        strategy_id=strategy_id, suspended=suspended,
        trailing_n=len(realized), mean_fwd10=mean10, reason_kr=reason,
    )


def update_all(fwd: pd.DataFrame, strategy_ids: list[str]) -> list[BreakerDecision]:
    """Weekly re-evaluation: update persisted state for every strategy.

    Returns:
        Decisions (caller sends Telegram notices for state CHANGES).
    """
    state = load_state()
    decisions = []
    for sid in strategy_ids:
        decision = evaluate(sid, fwd)
        prev = state.get(sid, {}).get("suspended", False)
        state[sid] = {
            "suspended": decision.suspended,
            "since": str(date.today()) if decision.suspended and not prev else state.get(sid, {}).get("since"),
            "mean_fwd10": decision.mean_fwd10,
        }
        if decision.suspended != prev:
            logger.warning("circuit breaker %s: %s -> %s (%s)", sid, prev, decision.suspended, decision.reason_kr)
        decisions.append(decision)
    save_state(state)
    return decisions
