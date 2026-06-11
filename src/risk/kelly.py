"""Half-Kelly position-size HINT (spec §8) — a hint, never an instruction.

Kelly fraction f* = W - (1-W)/B, where W = win rate, B = avg win / |avg loss|.
We display HALF Kelly, capped, and refuse to hint on low samples.
"""

import math

from config import settings
from src.backtest.confidence import ConfidenceReport

KELLY_CAP = 0.25  # never hint more than 25% of capital


def half_kelly_fraction(conf: ConfidenceReport) -> float | None:
    """Half-Kelly fraction from per-ticker confidence stats.

    Returns:
        Fraction 0..KELLY_CAP, or None when stats are insufficient
        (low sample, no losses recorded, or negative edge).
    """
    if conf.n_trades < settings.CONF_MIN_TRADES:
        return None
    if math.isnan(conf.avg_win) or math.isnan(conf.avg_loss) or conf.avg_loss >= 0:
        return None
    b = conf.avg_win / abs(conf.avg_loss)
    if b <= 0:
        return None
    f = conf.win_rate - (1 - conf.win_rate) / b
    if f <= 0:
        return None
    return min(f / 2, KELLY_CAP)


def kelly_hint_kr(conf: ConfidenceReport) -> str:
    """Korean display string for the report's 매매 계획 block."""
    f = half_kelly_fraction(conf)
    if f is None:
        if conf.n_trades < settings.CONF_MIN_TRADES:
            return f"표본 부족 ({conf.n_trades}건) — 제안 불가"
        return "엣지 불충분 — 제안 불가"
    return f"자본의 {f * 100:.0f}% (하프 켈리, 참고용)"
