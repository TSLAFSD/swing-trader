"""KR OHLCV fetcher with triple-source fallback, per ticker:

1. FinanceDataReader (primary; soft timeout via worker thread)
2. pykrx (retry + exponential backoff; adjusted=True)
3. yfinance with .KS/.KQ suffix (last resort — KRX blocks some cloud IPs;
   weaker KOSDAQ coverage / volume accuracy, so usage is flagged upstream)

All sources must return split/dividend-adjusted OHLCV. The source that served
each ticker is recorded in the `source` column and in the returned summary.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import date, timedelta

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

SOURCE_FDR = "fdr"
SOURCE_PYKRX = "pykrx"
SOURCE_YFINANCE = "yfinance_kr"

_YF_SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}


def _canonical(df: pd.DataFrame, ticker: str, source: str) -> pd.DataFrame:
    """Normalize a per-ticker OHLCV frame to the store's canonical long format.

    Drops halted-day artifacts (nonpositive OHLC) — KR sources return 0-price
    rows for trading halts, which would poison downstream min/max and ratio
    math (no forward-fill invariant: bad bar -> excluded).
    """
    df = df.dropna(subset=["close"])
    df = df[(df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)]
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": pd.to_datetime(df.index).date,
            "open": df["open"].to_numpy(dtype=float),
            "high": df["high"].to_numpy(dtype=float),
            "low": df["low"].to_numpy(dtype=float),
            "close": df["close"].to_numpy(dtype=float),
            "volume": df["volume"].to_numpy(dtype=float),
            "source": source,
        }
    )


def _fetch_fdr(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch via FinanceDataReader with a soft timeout (worker thread)."""
    import FinanceDataReader as fdr

    def call() -> pd.DataFrame:
        return fdr.DataReader(ticker, start, end)

    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            raw = pool.submit(call).result(timeout=settings.KR_FETCH_TIMEOUT_SEC)
        except FutureTimeoutError as exc:
            raise TimeoutError(f"FDR timed out after {settings.KR_FETCH_TIMEOUT_SEC}s") from exc
    if raw is None or raw.empty:
        raise ValueError("FDR returned empty frame")
    raw = raw.rename(columns=str.lower)
    return _canonical(raw, ticker, SOURCE_FDR)


def _fetch_pykrx(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch via pykrx with retry + exponential backoff; adjusted prices."""
    from pykrx import stock

    last_exc: Exception | None = None
    for attempt in range(settings.KR_RETRY_ATTEMPTS):
        try:
            raw = stock.get_market_ohlcv(
                start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker, adjusted=True
            )
            if raw is None or raw.empty:
                raise ValueError("pykrx returned empty frame")
            raw = raw.rename(
                columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}
            )
            return _canonical(raw, ticker, SOURCE_PYKRX)
        except Exception as exc:  # noqa: BLE001 - retry any source failure
            last_exc = exc
            backoff = settings.KR_RETRY_BACKOFF_BASE_SEC * (2**attempt)
            logger.warning("pykrx %s attempt %d failed (%s); backoff %.1fs", ticker, attempt + 1, exc, backoff)
            time.sleep(backoff)
    raise RuntimeError(f"pykrx failed after {settings.KR_RETRY_ATTEMPTS} attempts") from last_exc


def _fetch_yfinance_kr(ticker: str, start: date, end: date, market: str | None) -> pd.DataFrame:
    """Fetch via yfinance using .KS/.KQ suffix (last resort)."""
    import yfinance as yf

    suffixes = [_YF_SUFFIX[market]] if market in _YF_SUFFIX else [".KS", ".KQ"]
    last_exc: Exception | None = None
    for suffix in suffixes:
        try:
            raw = yf.download(
                f"{ticker}{suffix}",
                start=start,
                end=end + timedelta(days=1),
                auto_adjust=True,
                threads=False,
                progress=False,
            )
            if raw is None or raw.empty:
                raise ValueError(f"yfinance empty for {ticker}{suffix}")
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns=str.lower)
            return _canonical(raw, ticker, SOURCE_YFINANCE)
        except Exception as exc:  # noqa: BLE001 - try next suffix
            last_exc = exc
    raise RuntimeError(f"yfinance KR failed for {ticker}") from last_exc


def fetch_kr_ohlcv(
    tickers: list[str],
    start: date | None = None,
    end: date | None = None,
    markets: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Fetch adjusted daily OHLCV for KR tickers, sequentially, with fallback.

    Args:
        tickers: 6-digit KRX codes.
        start: Inclusive start date; defaults to HISTORY_YEARS ago.
        end: Inclusive end date; defaults to today.
        markets: Optional {ticker: "KOSPI"|"KOSDAQ"} map for the yfinance suffix.

    Returns:
        (canonical long-format frame, {ticker: source_used}).
        Tickers failing all three sources are absent from both (logged as errors).
    """
    start = start or (date.today() - timedelta(days=365 * settings.HISTORY_YEARS))
    end = end or date.today()
    markets = markets or {}
    frames: list[pd.DataFrame] = []
    sources: dict[str, str] = {}
    for ticker in tickers:
        frame: pd.DataFrame | None = None
        for fetch in (
            lambda t=ticker: _fetch_fdr(t, start, end),
            lambda t=ticker: _fetch_pykrx(t, start, end),
            lambda t=ticker: _fetch_yfinance_kr(t, start, end, markets.get(t)),
        ):
            try:
                frame = fetch()
                break
            except Exception as exc:  # noqa: BLE001 - fall through to next source
                logger.warning("kr_fetcher %s: source failed: %s", ticker, exc)
        if frame is None or frame.empty:
            logger.error("kr_fetcher %s: ALL THREE sources failed", ticker)
            continue
        source = frame["source"].iloc[0]
        sources[ticker] = source
        logger.info("kr_fetcher %s: %d rows via %s", ticker, len(frame), source)
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return result, sources


def yfinance_fallback_used(sources: dict[str, str]) -> bool:
    """True if any ticker was served by the 3rd source (health-check flag)."""
    return any(s == SOURCE_YFINANCE for s in sources.values())
