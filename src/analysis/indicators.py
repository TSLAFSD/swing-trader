"""Bulk indicator computation (pandas-ta) + cross-sectional metrics.

Per-ticker: compute_indicators() appends all standing indicator columns.
Cross-sectional (universe-level): rs_momentum_percentile(), breadth_pct().

NaN policy: NEVER forward-fill. Tickers with insufficient history are excluded
by callers per strategy min_bars; cross-sectional denominators exclude tickers
whose required inputs are NaN.
"""

import logging

import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)

SMA_LENGTHS = (5, 10, 20, 50, 60, 120, 200)
EMA_LENGTHS = (12, 26)

# Cross-sectional momentum: mean of 3m and 6m returns EXCLUDING the most
# recent month (21 trading days). 63/126 = 3m/6m in trading days.
RS_SKIP = 21
RS_SHORT = 63
RS_LONG = 126


def _col(df: pd.DataFrame | None, prefix: str, index: pd.Index | None = None) -> pd.Series:
    """Return the first column starting with prefix from a pandas-ta result.

    pandas-ta returns None when the input series is shorter than the
    indicator's minimum window — per the no-fill policy that maps to an
    all-NaN column (requires index).
    """
    if df is None:
        if index is None:
            raise ValueError(f"pandas-ta returned None for {prefix!r} and no index given")
        return pd.Series(np.nan, index=index)
    for name in df.columns:
        if str(name).startswith(prefix):
            return df[name]
    raise KeyError(f"no column starting with {prefix!r} in {list(df.columns)}")


def _series(result: pd.Series | None, index: pd.Index) -> pd.Series:
    """Map a pandas-ta single-Series result to all-NaN when history is too short."""
    if result is None:
        return pd.Series(np.nan, index=index)
    return result


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Append all standing indicators to a per-ticker OHLCV frame.

    Args:
        df: Frame with columns open/high/low/close/volume, ascending date order.

    Returns:
        Copy of df with indicator columns appended (NaN where undefined).
    """
    out = df.copy()
    close, high, low, vol = out["close"], out["high"], out["low"], out["volume"]

    idx0 = out.index
    for n in SMA_LENGTHS:
        out[f"sma{n}"] = _series(ta.sma(close, length=n), idx0)
    for n in EMA_LENGTHS:
        out[f"ema{n}"] = _series(ta.ema(close, length=n), idx0)
    out["rsi2"] = _series(ta.rsi(close, length=2), idx0)
    out["rsi14"] = _series(ta.rsi(close, length=14), idx0)

    idx = out.index
    macd = ta.macd(close)
    out["macd"] = _col(macd, "MACD_", idx)
    out["macd_signal"] = _col(macd, "MACDs_", idx)
    out["macd_hist"] = _col(macd, "MACDh_", idx)

    bb = ta.bbands(close, length=20, std=2)
    out["bb_lower"] = _col(bb, "BBL_", idx)
    out["bb_mid"] = _col(bb, "BBM_", idx)
    out["bb_upper"] = _col(bb, "BBU_", idx)

    kc = ta.kc(high, low, close, length=20, scalar=1.5)
    out["kc_lower"] = _col(kc, "KCL", idx)
    out["kc_mid"] = _col(kc, "KCB", idx)
    out["kc_upper"] = _col(kc, "KCU", idx)

    adx = ta.adx(high, low, close, length=14)
    out["adx14"] = _col(adx, "ADX_", idx)

    stoch = ta.stoch(high, low, close)
    out["stoch_k"] = _col(stoch, "STOCHk_", idx)
    out["stoch_d"] = _col(stoch, "STOCHd_", idx)

    out["atr14"] = _series(ta.atr(high, low, close, length=14), idx)
    out["obv"] = _series(ta.obv(close, vol), idx)
    # 0 -> NaN (same defense as zscore20's std): strategies divide by vol_ma20
    # and a 20-day zero-volume stretch would otherwise produce inf ratios.
    out["vol_ma20"] = _series(ta.sma(vol, length=20), idx).replace(0.0, np.nan)

    # Z-score vs SMA20 — standing column for strategy ② and reports.
    rolling_std20 = close.rolling(20).std(ddof=0)
    out["zscore20"] = (close - out["sma20"]) / rolling_std20.replace(0.0, np.nan)

    # TTM-style squeeze: BB fully inside Keltner.
    out["squeeze_on"] = (out["bb_lower"] > out["kc_lower"]) & (out["bb_upper"] < out["kc_upper"])

    # Momentum proxy for squeeze release: 20-day linear-regression slope.
    out["linreg_slope20"] = _series(ta.linreg(close, length=20, slope=True), idx)

    # Prior 60-day high EXCLUDING today (breakout reference).
    out["prior_high60"] = high.shift(1).rolling(60).max()

    # 1-day move (anomaly guard input).
    out["pct_change_1d"] = close.pct_change() * 100.0

    return out


def rs_composite(close: pd.Series) -> float:
    """Composite momentum for one ticker: mean(3m, 6m return) excl. last month.

    Returns:
        Composite return, or NaN if history is insufficient.
    """
    if len(close) < RS_LONG + RS_SKIP + 1:
        return float("nan")
    ref = close.iloc[-1 - RS_SKIP]
    r3 = ref / close.iloc[-1 - RS_SKIP - RS_SHORT] - 1.0
    r6 = ref / close.iloc[-1 - RS_SKIP - RS_LONG] - 1.0
    return float((r3 + r6) / 2.0)


def rs_momentum_percentile(closes: dict[str, pd.Series]) -> dict[str, float]:
    """Percentile-rank (0-100) every ticker's composite momentum across the universe.

    Tickers with insufficient history are EXCLUDED from the denominator and
    absent from the result (never silently ranked).

    Args:
        closes: {ticker: close series, ascending date order}.

    Returns:
        {ticker: percentile 0-100} for tickers with enough history.
    """
    scores = {t: rs_composite(s) for t, s in closes.items()}
    valid = pd.Series({t: v for t, v in scores.items() if not np.isnan(v)})
    if valid.empty:
        return {}
    pct = valid.rank(pct=True) * 100.0
    logger.info("rs momentum: ranked %d/%d tickers", len(valid), len(closes))
    return pct.to_dict()


def breadth_pct(frames: dict[str, pd.DataFrame]) -> float:
    """Percent of universe tickers whose last close is above their SMA60.

    Tickers whose SMA60 is NaN (short history) are excluded from the denominator.

    Args:
        frames: {ticker: indicator frame from compute_indicators()}.

    Returns:
        Breadth percentage 0-100 (NaN if no ticker qualifies).
    """
    above = total = 0
    for df in frames.values():
        if df.empty or "sma60" not in df.columns:
            continue
        last = df.iloc[-1]
        if pd.isna(last["sma60"]):
            continue
        total += 1
        if last["close"] > last["sma60"]:
            above += 1
    if total == 0:
        return float("nan")
    return above / total * 100.0
