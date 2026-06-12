"""Distribution monitor (U3/C-2) — sell-side VPA check for HELD positions.

Not a strategy (no cap slot): confirmed scans run the mirrored Wyckoff
functions on every held ticker. A RECENT Buying Climax / UTAD raises a
Korean warning; concurrent demand exhaustion merges into the same message.
Warning only — never an automatic sell.
"""

import logging

import pandas as pd

from src.analysis.base_strategy import load_strategy_config
from src.analysis.wyckoff_vpa import (
    detect_buying_climax,
    detect_demand_exhaustion,
    detect_liquidity_high,
    weis_waves,
)

logger = logging.getLogger(__name__)

RECENT_BARS = 5  # climax older than this is stale — no alert


def check_distribution(df: pd.DataFrame, name: str, ticker: str) -> str | None:
    """Korean distribution warning for one held ticker, or None.

    Args:
        df: Adjusted OHLCV (canonical columns), ascending dates.
        name: Display name.
        ticker: Ticker code.

    Returns:
        Alert text when a recent UTAD fired (exhaustion merged in), else None.
    """
    vpa = load_strategy_config()["strategies"]["wyckoff_spring"]["params"]["vpa"]
    if len(df) < vpa["lookback"] + vpa["pivot_strength"]:
        return None
    level = detect_liquidity_high(
        df, lookback=vpa["lookback"], pivot_strength=vpa["pivot_strength"],
        equal_high_pct=vpa["equal_low_pct"],
    )
    if level is None:
        return None
    climax = detect_buying_climax(
        df, level.level, vol_ma_days=vpa["vol_ma_days"],
        vol_mult=vpa["vol_mult"], wick_body_ratio=vpa["wick_body_ratio"],
    )
    if climax is None:
        return None
    waves = weis_waves(df, zigzag_pct=vpa["zigzag_pct"])
    exhaustion = detect_demand_exhaustion(
        waves, climax, retest_window=vpa["retest_window"], exhaust_ratio=vpa["exhaust_ratio"],
    )
    # Freshness: alert while the EVIDENCE is fresh — a just-fired UTAD, or a
    # demand-exhaustion retest that completed within the recent window.
    n = len(df)
    climax_fresh = climax.sweep_idx >= n - RECENT_BARS
    exhaustion_fresh = False
    if exhaustion is not None:
        pos = df.index[df["date"] == exhaustion.retest_date]
        exhaustion_fresh = bool(len(pos)) and (n - 1 - pos[0]) <= RECENT_BARS
    if not (climax_fresh or exhaustion_fresh):
        return None
    kind = "윗꼬리 거부" if climax.recovery_type == "rejection_wick" else "종가 회귀"
    text = (
        f"🚨 [분산 징후] {name}({ticker}) — 고점 {level.level:,.0f} 상향 이탈 후 "
        f"거래량 {climax.volume_ratio:.1f}배 + {kind} (UTAD 의심), 익절 검토 권고"
    )
    if exhaustion is not None:
        text += (
            f"\n   수요 고갈 동반: 재상승 시도 거래량이 클라이맥스의 "
            f"{exhaustion.test_volume_ratio:.0%}에 불과 — 상승 동력 소진 신호"
        )
    return text
