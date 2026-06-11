"""Shared exit engine: identical rules for live position monitoring and backtests.

Three modes, selected per strategy via `exit_mode` in strategies.yaml:
  1. fixed        — static stop-loss / take-profit percentages.
  2. atr_trailing — chandelier stop: highest close since entry - k * ATR(14).
  3. roi_table    — time-decay required-profit ladder, e.g. {0: .15, 5: .08, 10: .03}.

All modes also honor a strategy time stop and the global max holding period.
Pure functions only — no I/O, no state — so both consumers behave identically.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_HOLDING_DAYS = 20  # global swing-trade ceiling (spec: holding 3-20 days)

# Default ROI ladder: required profit to exit shrinks with holding days.
DEFAULT_ROI_TABLE: dict[int, float] = {0: 0.15, 5: 0.08, 10: 0.03}


@dataclass
class PositionState:
    """Everything the exit engine needs to know about an open position."""

    entry_price: float
    current_close: float
    highest_close_since_entry: float
    days_held: int  # trading days since entry (entry day = 0)
    atr: float | None = None  # latest ATR(14); required for atr_trailing
    stop_loss: float | None = None  # absolute level (from Signal)
    take_profit: float | None = None  # absolute level (from Signal)


def profit_pct(state: PositionState) -> float:
    """Unrealized return fraction (0.05 = +5%)."""
    return state.current_close / state.entry_price - 1.0


def atr_trailing_stop(highest_close: float, atr: float, k: float) -> float:
    """Chandelier stop level: highest close since entry - k * ATR."""
    return highest_close - k * atr


def roi_required(days_held: int, table: dict[int, float]) -> float:
    """Required profit for the ROI ladder at a given holding age.

    Uses the entry with the largest threshold <= days_held.
    """
    eligible = [d for d in table if d <= days_held]
    return table[max(eligible)] if eligible else float("inf")


def check_exit(
    mode: str,
    state: PositionState,
    *,
    atr_k: float = 3.0,
    roi_table: dict[int, float] | None = None,
    time_stop_days: int | None = None,
    max_holding_days: int = MAX_HOLDING_DAYS,
) -> str | None:
    """Evaluate engine-level exit rules for one position on one bar.

    Strategy-specific sell conditions (e.g. RSI > 70) live on the strategy
    classes (`should_exit`) and are checked by the caller IN ADDITION to this.

    Args:
        mode: "fixed" | "atr_trailing" | "roi_table".
        state: Current position snapshot.
        atr_k: Chandelier multiplier (atr_trailing mode).
        roi_table: Ladder override; DEFAULT_ROI_TABLE when None (roi_table mode).
        time_stop_days: Strategy time stop (None = none).
        max_holding_days: Global holding ceiling.

    Returns:
        Korean exit reason, or None to keep holding.

    Raises:
        ValueError: Unknown mode, or atr_trailing without ATR.
    """
    if mode not in ("fixed", "atr_trailing", "roi_table"):
        raise ValueError(f"unknown exit_mode {mode!r}")

    if mode == "fixed":
        if state.stop_loss is not None and state.current_close <= state.stop_loss:
            return f"손절 도달 ({state.stop_loss:,.2f})"
        if state.take_profit is not None and state.current_close >= state.take_profit:
            return f"목표가 도달 ({state.take_profit:,.2f})"

    elif mode == "atr_trailing":
        if state.atr is None:
            raise ValueError("atr_trailing requires state.atr")
        # Hard stop (e.g. below squeeze range / spring low) still applies first.
        if state.stop_loss is not None and state.current_close <= state.stop_loss:
            return f"손절 도달 ({state.stop_loss:,.2f})"
        trail = atr_trailing_stop(state.highest_close_since_entry, state.atr, atr_k)
        if state.current_close <= trail:
            return f"ATR 추적 손절 ({trail:,.2f})"

    else:  # roi_table
        table = roi_table or DEFAULT_ROI_TABLE
        if state.stop_loss is not None and state.current_close <= state.stop_loss:
            return f"손절 도달 ({state.stop_loss:,.2f})"
        required = roi_required(state.days_held, table)
        if profit_pct(state) >= required:
            return f"ROI 사다리 충족 (+{profit_pct(state) * 100:.1f}% ≥ {required * 100:.0f}%)"

    if time_stop_days is not None and state.days_held >= time_stop_days:
        return f"보유기간 초과 ({time_stop_days}일 타임스톱)"
    if state.days_held >= max_holding_days:
        return f"최대 보유기간 도달 ({max_holding_days}일)"
    return None
