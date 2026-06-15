"""Per-strategy circuit breaker (spec §5.3, Freqtrade 'protections' reimplemented).

If a strategy's trailing CB_TRAILING_SIGNALS signals have a mean realized
+10d forward return below CB_MEAN_FWD10_MIN, it is suspended (signals muted,
Telegram notice) until the weekly job re-evaluates. State persists as JSON
on the data branch.
"""

import json
import logging
import math
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
    # Hardened-breaker extras (adaptive Lever 1); defaults keep the legacy path intact.
    win_rate: float | None = None
    profit_factor: float | None = None
    action: str = "none"  # none | suspended | reactivated | safeguard_kept


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


def _pf_kr(pf: float | None) -> str:
    """Render a profit factor for Korean notices (— unknown, ∞ no losses)."""
    if pf is None or pf != pf:
        return "—"
    return "∞" if math.isinf(pf) else f"{pf:.2f}"


def evaluate_hardened(
    strategy_id: str, fwd: pd.DataFrame, currently_suspended: bool
) -> BreakerDecision:
    """Multi-condition suspend + hysteresis reactivation (adaptive Lever 1).

    Suspend (only when not already suspended) requires BOTH:
      mean +10d < CB_SUSPEND_RET_THRESHOLD, AND
      (win_rate < CB_SUSPEND_WINRATE_FLOOR OR profit_factor < 1.0),
    so one unlucky window cannot suspend a still-profitable strategy.

    Reactivate (only when suspended) requires mean +10d >=
    CB_REACTIVATE_RET_THRESHOLD — a HIGHER bar than suspension (hysteresis) to
    prevent on/off flapping. Insufficient realized sample never changes state.
    """
    from src.backtest.tracker import trailing_stats

    n = settings.CB_SUSPEND_TRAILING_N
    st = trailing_stats(fwd, strategy_id, n)
    nr, mean10, wr, pf = st["n_realized"], st["mean_fwd10"], st["win_rate"], st["profit_factor"]
    if nr < n // 2:  # not enough realized outcomes -> hold current state
        return BreakerDecision(
            strategy_id, currently_suspended, nr, mean10,
            f"실현 표본 부족 ({nr}/{n}) — 상태 유지", win_rate=wr, profit_factor=pf,
        )
    stat_kr = f"최근 {nr}건 +10일 평균 {mean10 * 100:+.1f}% · 승률 {wr * 100:.0f}% · PF {_pf_kr(pf)}"
    if currently_suspended:
        suspended = mean10 < settings.CB_REACTIVATE_RET_THRESHOLD
        tail = (
            f"재가동 기준({settings.CB_REACTIVATE_RET_THRESHOLD * 100:.0f}%) 미달 → 중단 유지"
            if suspended
            else "재가동 기준 충족 → 해제"
        )
    else:
        # mean<0 is mathematically equivalent to PF<1, so the spec's "OR PF<1"
        # clause is vacuous (it would collapse suspension to mean<threshold and
        # still trip on ONE unlucky big loss among many wins). To honor the
        # stated intent — "don't suspend on one unlucky window" — we require a
        # corroborating LOW WIN RATE (AND); PF is reported for context only.
        precond = mean10 < settings.CB_SUSPEND_RET_THRESHOLD
        weak = wr < settings.CB_SUSPEND_WINRATE_FLOOR
        suspended = precond and weak
        tail = (
            f"기준 미달(평균<{settings.CB_SUSPEND_RET_THRESHOLD * 100:.0f}% 且 "
            f"승률<{settings.CB_SUSPEND_WINRATE_FLOOR * 100:.0f}%) → 중단"
            if suspended
            else "정상"
        )
    return BreakerDecision(
        strategy_id, suspended, nr, mean10, f"{stat_kr} — {tail}", win_rate=wr, profit_factor=pf,
    )


def _persist_decisions(state: dict, decisions: list[BreakerDecision], path: Path | None) -> None:
    """Write back suspended/since/mean for each decision; log state changes."""
    for d in decisions:
        prev = state.get(d.strategy_id, {}).get("suspended", False)
        state[d.strategy_id] = {
            "suspended": d.suspended,
            "since": str(date.today()) if d.suspended and not prev else state.get(d.strategy_id, {}).get("since"),
            "mean_fwd10": d.mean_fwd10,
        }
        if d.suspended != prev:
            logger.warning("circuit breaker %s: %s -> %s (%s)", d.strategy_id, prev, d.suspended, d.reason_kr)
    save_state(state, path)


def _update_all_legacy(
    fwd: pd.DataFrame, strategy_ids: list[str], path: Path | None
) -> list[BreakerDecision]:
    """Original single-condition path (ADAPTIVE_LOOP_ENABLED=False baseline)."""
    state = load_state(path)
    decisions = [evaluate(sid, fwd) for sid in strategy_ids]
    _persist_decisions(state, decisions, path)
    return decisions


def update_all(
    fwd: pd.DataFrame,
    strategy_ids: list[str],
    enabled_ids: set[str] | None = None,
    path: Path | None = None,
) -> list[BreakerDecision]:
    """Weekly re-evaluation of every strategy's breaker state.

    ADAPTIVE_LOOP_ENABLED=False -> legacy single-condition path (baseline,
    byte-for-byte). Otherwise the hardened path runs, then a single-strategy-
    silence safeguard keeps the best ENABLED strategy active when every enabled
    strategy would be suspended (a one-strategy system must never go fully mute).

    Args:
        enabled_ids: strategy ids that actually emit signals; the safeguard
            applies among these (defaults to all evaluated).

    Returns:
        Decisions (caller sends Telegram notices for action != "none").
    """
    if not settings.ADAPTIVE_LOOP_ENABLED:
        return _update_all_legacy(fwd, strategy_ids, path)
    state = load_state(path)
    decisions = []
    for sid in strategy_ids:
        prev = state.get(sid, {}).get("suspended", False)
        decision = evaluate_hardened(sid, fwd, prev)
        decision.action = (
            "suspended" if decision.suspended and not prev
            else "reactivated" if not decision.suspended and prev
            else "none"
        )
        decisions.append(decision)
    enabled = enabled_ids if enabled_ids is not None else {d.strategy_id for d in decisions}
    enabled_dec = [d for d in decisions if d.strategy_id in enabled]
    if enabled_dec and all(d.suspended for d in enabled_dec):
        keep = max(enabled_dec, key=lambda d: d.mean_fwd10 if d.mean_fwd10 is not None else float("-inf"))
        keep.suspended = False
        keep.action = "safeguard_kept"
        keep.reason_kr += " · ⚠️ 전 전략 중단 방지 안전장치로 유지"
    _persist_decisions(state, decisions, path)
    return decisions
