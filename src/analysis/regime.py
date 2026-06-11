"""Dual market-regime filter: index trend + universe breadth, with VIX context.

(a) Index below SMA60 -> BUY strength x index_downgrade_factor.
(b) Breadth below threshold -> additional downgrade (mega-cap distortion guard).
VIX is fetched for DISPLAY ONLY — it never gates signals.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

INDEX_SYMBOL = {"kr": "KS11", "us": "^GSPC"}
INDEX_NAME_KR = {"kr": "코스피", "us": "S&P500"}

# Regime thresholds (downgrades multiply; hard_block overrides both).
INDEX_SMA = 60
BREADTH_MIN_PCT = 30.0
INDEX_DOWNGRADE_FACTOR = 0.5
BREADTH_DOWNGRADE_FACTOR = 0.7
HARD_BLOCK = False  # config: if True, weak regime drops BUY signals entirely


@dataclass
class RegimeState:
    """Snapshot of one market's regime at scan time."""

    market: str
    index_value: float | None
    index_sma60: float | None
    index_above_sma60: bool | None
    breadth_pct: float | None
    breadth_ok: bool | None
    vix: float | None
    downgrade_factor: float  # 1.0 = no downgrade
    label_kr: str

    @property
    def weak(self) -> bool:
        """True if any downgrade applies."""
        return self.downgrade_factor < 1.0


def _fetch_index_series(market: str) -> pd.Series | None:
    """Fetch ~1y of index closes (FDR for KR, yfinance for US)."""
    symbol = INDEX_SYMBOL[market]
    start = date.today() - timedelta(days=400)
    try:
        if market == "kr":
            import FinanceDataReader as fdr

            df = fdr.DataReader(symbol, start)
            return df["Close"].dropna()
        import yfinance as yf

        df = yf.download(symbol, start=start, auto_adjust=True, threads=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df["Close"].dropna()
    except Exception:
        logger.exception("regime: index fetch failed for %s", symbol)
        return None


def _fetch_vix() -> float | None:
    """Fetch the latest ^VIX close (display-only context)."""
    try:
        import yfinance as yf

        df = yf.download("^VIX", period="5d", threads=False, progress=False, auto_adjust=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return float(df["Close"].dropna().iloc[-1])
    except Exception:
        logger.exception("regime: VIX fetch failed")
        return None


def get_regime(market: str, breadth: float | None) -> RegimeState:
    """Assess the market regime for signal downgrading.

    A failed index fetch yields NO downgrade (fail-open) but is labeled so the
    health check shows the gauge was unavailable.

    Args:
        market: "us" | "kr".
        breadth: % of universe above SMA60, from indicators.breadth_pct().

    Returns:
        RegimeState with the combined downgrade factor and a Korean label.
    """
    series = _fetch_index_series(market)
    index_value = index_sma60 = None
    index_above: bool | None = None
    if series is not None and len(series) >= INDEX_SMA:
        index_value = float(series.iloc[-1])
        index_sma60 = float(series.rolling(INDEX_SMA).mean().iloc[-1])
        index_above = index_value > index_sma60

    breadth_ok: bool | None = None
    if breadth is not None and not pd.isna(breadth):
        breadth_ok = breadth >= BREADTH_MIN_PCT
    else:
        breadth = None

    factor = 1.0
    parts: list[str] = []
    name = INDEX_NAME_KR[market]
    if index_above is False:
        factor *= INDEX_DOWNGRADE_FACTOR
        parts.append(f"⚠️ 시장 약세 국면 ({name} 60일선 아래)")
    elif index_above is True:
        parts.append(f"{name} 60일선 위 (양호)")
    else:
        parts.append(f"{name} 지수 조회 실패 — 국면 판단 불가")
    if breadth_ok is False:
        factor *= BREADTH_DOWNGRADE_FACTOR
        parts.append(f"⚠️ 시장 내부 체력 약함 (60일선 위 종목 {breadth:.0f}%)")
    elif breadth_ok is True:
        parts.append(f"시장 폭 양호 (60일선 위 종목 {breadth:.0f}%)")

    vix = _fetch_vix() if market == "us" else None
    if vix is not None:
        parts.append(f"VIX {vix:.1f}")

    return RegimeState(
        market=market,
        index_value=index_value,
        index_sma60=index_sma60,
        index_above_sma60=index_above,
        breadth_pct=breadth,
        breadth_ok=breadth_ok,
        vix=vix,
        downgrade_factor=factor,
        label_kr=" · ".join(parts),
    )
