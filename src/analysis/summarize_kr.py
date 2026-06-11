"""Plain-Korean narration of indicator states for a non-chartist owner.

Every sentence includes the actual numbers (precision matters).
Code/comments stay in English; OUTPUT strings are Korean by design.
"""

import pandas as pd


def _fmt(value: float, market: str) -> str:
    """Format a price for the market's currency convention."""
    if market.lower() == "kr":
        return f"{value:,.0f}원"
    return f"${value:,.2f}"


def summarize_kr(row: pd.Series, market: str = "us") -> list[str]:
    """Translate the latest indicator row into plain-Korean sentences.

    Args:
        row: Last row of a compute_indicators() frame.
        market: "us" or "kr" (currency formatting).

    Returns:
        List of Korean sentences; indicators with NaN are skipped silently.
    """
    lines: list[str] = []
    close = row["close"]

    rsi = row.get("rsi14")
    if pd.notna(rsi):
        state = "과매도 구간" if rsi < 30 else "과열 구간" if rsi > 70 else "중립 구간"
        lines.append(f"RSI {rsi:.0f} — {state}")

    z = row.get("zscore20")
    if pd.notna(z):
        if z <= -2.5:
            state = "통계적 극단 과매도"
        elif z <= -1.5:
            state = "통계적 과매도 접근"
        elif z >= 2.5:
            state = "통계적 과열 (평균 대비 매우 높음)"
        elif z >= 1.5:
            state = "평균 대비 높은 수준"
        else:
            state = "평균 부근"
        lines.append(f"현재 주가는 20일 평균 대비 {z:+.1f} 표준편차 — {state}")

    sma200 = row.get("sma200")
    if pd.notna(sma200):
        trend = "위 — 장기 상승 추세" if close > sma200 else "아래 — 장기 하락 추세"
        lines.append(f"주가가 200일선({_fmt(sma200, market)}) {trend}")

    sma20, sma60 = row.get("sma20"), row.get("sma60")
    if pd.notna(sma20) and pd.notna(sma60):
        if close > sma20 and sma20 > sma60:
            lines.append("주가가 20일선·60일선 위 — 중기 상승 정배열")
        elif close < sma20 and sma20 < sma60:
            lines.append("주가가 20일선·60일선 아래 — 중기 하락 배열")
        else:
            lines.append("20일선과 60일선 사이 혼조 — 중기 방향 탐색 구간")

    bb_lower, bb_upper = row.get("bb_lower"), row.get("bb_upper")
    if pd.notna(bb_lower) and pd.notna(bb_upper) and bb_upper > bb_lower:
        pos = (close - bb_lower) / (bb_upper - bb_lower) * 100
        lines.append(f"볼린저밴드 내 위치 {pos:.0f}% (0%=하단, 100%=상단)")

    macd_hist = row.get("macd_hist")
    if pd.notna(macd_hist):
        state = "매수 우위 (시그널선 위)" if macd_hist > 0 else "매도 우위 (시그널선 아래)"
        lines.append(f"MACD 히스토그램 {macd_hist:+.2f} — {state}")

    adx = row.get("adx14")
    if pd.notna(adx):
        state = "추세 강함" if adx > 25 else "추세 형성 중" if adx > 20 else "추세 약함 (횡보 성향)"
        lines.append(f"ADX {adx:.0f} — {state}")

    vol_ma = row.get("vol_ma20")
    if pd.notna(vol_ma) and vol_ma > 0:
        ratio = row["volume"] / vol_ma
        state = "평소보다 거래 활발" if ratio > 1.5 else "평소 수준" if ratio > 0.7 else "거래 한산"
        lines.append(f"거래량은 20일 평균의 {ratio:.1f}배 — {state}")

    if bool(row.get("squeeze_on", False)):
        lines.append("변동성 스퀴즈 진행 중 — 큰 움직임이 임박했을 가능성")

    return lines
