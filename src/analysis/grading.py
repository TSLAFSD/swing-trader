"""Composite grade A/B/C (U4/Part D) + entry zone + contrarian indicators.

Telegram cards show the GRADE; the report shows the same composite value and
its full derivation (산출 근거) — never two different numbers.
"""

import logging
from dataclasses import dataclass

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class Grade:
    """Composite grade with its disclosed derivation."""

    letter: str  # A | B | C
    value: float  # 0-100 composite
    basis_kr: str  # full derivation string (report)


def regime_score(downgrade_factor: float | None) -> float:
    """Map the regime downgrade factor to 100/50/0 (none/one/both downgrades)."""
    if downgrade_factor is None or downgrade_factor >= 0.99:
        return 100.0
    # Single downgrade: index x0.5 or breadth x0.7; both: 0.35.
    return 50.0 if downgrade_factor > 0.4 else 0.0


def composite_grade(strength: float, confidence_score: float, downgrade_factor: float | None) -> Grade:
    """Blend strength, confidence and regime into one A/B/C grade.

    Args:
        strength: Final (confidence-adjusted) signal strength 0-100.
        confidence_score: Per-ticker confidence 0-1.
        downgrade_factor: RegimeState.downgrade_factor (None = unknown -> 100).
    """
    reg = regime_score(downgrade_factor)
    conf = confidence_score * 100.0
    value = (
        strength * settings.GRADE_W_STRENGTH
        + conf * settings.GRADE_W_CONFIDENCE
        + reg * settings.GRADE_W_REGIME
    )
    letter = "A" if value >= settings.GRADE_A_MIN else "B" if value >= settings.GRADE_B_MIN else "C"
    basis = (
        f"강도 {strength:.0f}×{settings.GRADE_W_STRENGTH} + "
        f"신뢰도 {conf:.0f}×{settings.GRADE_W_CONFIDENCE} + "
        f"국면 {reg:.0f}×{settings.GRADE_W_REGIME} = {value:.0f} → {letter}"
    )
    return Grade(letter=letter, value=round(value, 1), basis_kr=basis)


def entry_zone_top(price: float, atr: float | None) -> float:
    """Upper bound of the entry zone: price + min(price*gap%, 0.5*ATR14).

    Above this = 추격 금지. Falls back to the gap% cap when ATR is missing.
    """
    cap = price * settings.GAP_ALERT_PCT / 100.0
    if atr is not None and atr == atr and atr > 0:
        cap = min(cap, 0.5 * atr)
    return round(price + cap, 4)


CONTRARIAN_CHECKS = [
    ("주가가 200일선 아래 (장기 하락 추세)",
     lambda r: pd.notna(r.get("sma200")) and r["close"] < r["sma200"]),
    ("MACD 히스토그램 음(-) — 단기 모멘텀 약화",
     lambda r: pd.notna(r.get("macd_hist")) and r["macd_hist"] < 0),
    ("RSI 70 초과 — 과열 구간",
     lambda r: pd.notna(r.get("rsi14")) and r["rsi14"] > 70),
    ("거래량이 평소의 0.7배 미만 — 참여 부족",
     lambda r: pd.notna(r.get("vol_ma20")) and r["vol_ma20"] > 0 and r["volume"] < 0.7 * r["vol_ma20"]),
    ("z-score +1.5 초과 — 평균 대비 이미 높음",
     lambda r: pd.notna(r.get("zscore20")) and r["zscore20"] > 1.5),
    ("60일선 하향 기울기 — 중기 추세 꺾임",
     lambda r: pd.notna(r.get("sma60_slope")) and r["sma60_slope"] < 0),
]


def contrarian_indicators(df_ind: pd.DataFrame) -> list[str]:
    """Korean labels of the contrarian (against-the-buy) indicators present."""
    row = df_ind.iloc[-1].copy()
    if "sma60" in df_ind.columns and len(df_ind) >= 6:
        row["sma60_slope"] = df_ind["sma60"].iloc[-1] - df_ind["sma60"].iloc[-6]
    return [label for label, check in CONTRARIAN_CHECKS if check(row)]
