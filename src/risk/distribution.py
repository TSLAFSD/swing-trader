"""Distribution monitor (U3/C-2) — sell-side VPA evidence, two consumers.

Held positions: confirmed scans call check_distribution() (Korean alert,
warning only — never an automatic sell). Signal candidates (2026-07-07
Part 3): the scan loop calls distribution_evidence() + candidate_tag_kr()
to badge suspected distribution ("설거지") — badge only, NEVER a block
(re-accumulation looks identical while forming; a later spring signal
re-recommends it if so).
"""

import logging
from dataclasses import dataclass

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
DIST_TAG_PREFIX = "⚠️ 분산 의심"


@dataclass(frozen=True)
class DistributionEvidence:
    """Sell-side VPA evidence for one ticker (UTAD-pattern)."""

    level: float  # broken liquidity high
    volume_ratio: float  # climax volume vs its MA
    recovery_type: str  # "rejection_wick" | close-regression variant
    climax_fresh: bool
    exhaustion_fresh: bool
    test_volume_ratio: float | None  # None when no demand exhaustion


def distribution_evidence(
    df: pd.DataFrame, recent_bars: int = RECENT_BARS
) -> DistributionEvidence | None:
    """Detect a recent UTAD (+ optional demand exhaustion) on one ticker.

    Args:
        df: Adjusted OHLCV (canonical columns), ascending dates.
        recent_bars: Freshness window; evidence older than this returns None.

    Returns:
        Evidence when a fresh UTAD fired, else None.
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
    n = len(df)
    climax_fresh = climax.sweep_idx >= n - recent_bars
    exhaustion_fresh = False
    if exhaustion is not None:
        pos = df.index[df["date"] == exhaustion.retest_date]
        exhaustion_fresh = bool(len(pos)) and (n - 1 - pos[0]) <= recent_bars
    if not (climax_fresh or exhaustion_fresh):
        return None
    return DistributionEvidence(
        level=level.level,
        volume_ratio=climax.volume_ratio,
        recovery_type=climax.recovery_type,
        climax_fresh=climax_fresh,
        exhaustion_fresh=exhaustion_fresh,
        test_volume_ratio=exhaustion.test_volume_ratio if exhaustion else None,
    )


def candidate_tag_kr(ev: DistributionEvidence) -> str:
    """One-line Korean badge for a SIGNAL CANDIDATE (advisory, never blocks)."""
    kind = "윗꼬리 거부" if ev.recovery_type == "rejection_wick" else "종가 회귀"
    tail = " · 수요 고갈 동반" if ev.test_volume_ratio is not None else ""
    return (
        f"{DIST_TAG_PREFIX} — 고점 돌파 후 거래량 {ev.volume_ratio:.1f}배 + {kind}"
        f" (UTAD/설거지 가능){tail} · 재매집일 수도 있어 참고만"
    )


def check_distribution(df: pd.DataFrame, name: str, ticker: str) -> str | None:
    """Korean distribution warning for one held ticker, or None.

    Args:
        df: Adjusted OHLCV (canonical columns), ascending dates.
        name: Display name.
        ticker: Ticker code.

    Returns:
        Alert text when a recent UTAD fired (exhaustion merged in), else None.
    """
    ev = distribution_evidence(df)
    if ev is None:
        return None
    kind = "윗꼬리 거부" if ev.recovery_type == "rejection_wick" else "종가 회귀"
    text = (
        f"🚨 [분산 징후] {name}({ticker}) — 고점 {ev.level:,.0f} 상향 이탈 후 "
        f"거래량 {ev.volume_ratio:.1f}배 + {kind} (UTAD 의심), 익절 검토 권고"
    )
    if ev.test_volume_ratio is not None:
        text += (
            f"\n   수요 고갈 동반: 재상승 시도 거래량이 클라이맥스의 "
            f"{ev.test_volume_ratio:.0%}에 불과 — 상승 동력 소진 신호"
        )
    return text
