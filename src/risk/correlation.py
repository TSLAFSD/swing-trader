"""Correlation warning (spec §8): new BUY vs held positions.

If a candidate's 60-day daily-return correlation with ANY held position
exceeds the threshold, the signal gets a diversification warning tag.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

CORR_WINDOW = 60
CORR_THRESHOLD = 0.7


def correlation_warning(
    candidate: str,
    closes_by_ticker: dict[str, pd.Series],
    held_tickers: list[str],
    names: dict[str, str] | None = None,
) -> str | None:
    """Korean warning when the candidate correlates highly with a held position.

    Args:
        candidate: BUY-signal ticker.
        closes_by_ticker: {ticker: close series, ascending} — must include the
            candidate and (where available) held tickers.
        held_tickers: Currently held tickers in the same market.
        names: Display names.

    Returns:
        Warning string, or None (no held positions / low correlation /
        insufficient overlapping history).
    """
    names = names or {}
    cand = closes_by_ticker.get(candidate)
    if cand is None or len(cand) < CORR_WINDOW + 1:
        return None
    cand_ret = cand.pct_change().tail(CORR_WINDOW).reset_index(drop=True)
    worst: tuple[str, float] | None = None
    for held in held_tickers:
        if held == candidate:
            continue
        series = closes_by_ticker.get(held)
        if series is None or len(series) < CORR_WINDOW + 1:
            continue
        held_ret = series.pct_change().tail(CORR_WINDOW).reset_index(drop=True)
        n = min(len(cand_ret), len(held_ret))
        corr = cand_ret.tail(n).reset_index(drop=True).corr(held_ret.tail(n).reset_index(drop=True))
        if pd.notna(corr) and corr > CORR_THRESHOLD and (worst is None or corr > worst[1]):
            worst = (held, float(corr))
    if worst is None:
        return None
    held, corr = worst
    return (
        f"⚠️ 보유 중인 {names.get(held, held)}과(와) 상관 높음 "
        f"(60일 상관계수 {corr:.2f}) — 분산 효과 낮음"
    )
