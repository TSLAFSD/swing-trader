"""US OHLCV fetcher via yfinance: batched 50 tickers + 2s sleep, adjusted prices.

yfinance with auto_adjust=True returns split/dividend-adjusted OHLC.
Output is the store's canonical long format.
"""

import logging
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from config import settings

logger = logging.getLogger(__name__)

SOURCE_NAME = "yfinance"


def _flatten_batch(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Convert yf.download group_by='ticker' output to canonical long format."""
    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        try:
            sub = raw[ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            logger.warning("us_fetcher: no data returned for %s", ticker)
            continue
        sub = sub.dropna(subset=["Close"])
        if sub.empty:
            logger.warning("us_fetcher: empty frame for %s", ticker)
            continue
        frames.append(
            pd.DataFrame(
                {
                    "ticker": ticker,
                    "date": pd.to_datetime(sub.index).date,
                    "open": sub["Open"].to_numpy(),
                    "high": sub["High"].to_numpy(),
                    "low": sub["Low"].to_numpy(),
                    "close": sub["Close"].to_numpy(),
                    "volume": sub["Volume"].to_numpy(dtype=float),
                    "source": SOURCE_NAME,
                }
            )
        )
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_us_ohlcv(
    tickers: list[str],
    start: date | None = None,
    end: date | None = None,
    batch_size: int = settings.US_BATCH_SIZE,
    sleep_sec: float = settings.US_BATCH_SLEEP_SEC,
) -> pd.DataFrame:
    """Fetch adjusted daily OHLCV for US tickers in rate-limited batches.

    Args:
        tickers: Ticker symbols (yfinance format).
        start: Inclusive start date; defaults to HISTORY_YEARS ago.
        end: Exclusive end date; defaults to tomorrow (include today's bar).
        batch_size: Tickers per yf.download call.
        sleep_sec: Sleep between batches.

    Returns:
        Canonical long-format frame (may be empty on total failure).
    """
    start = start or (date.today() - timedelta(days=365 * settings.HISTORY_YEARS))
    end = end or (date.today() + timedelta(days=1))
    frames: list[pd.DataFrame] = []
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        logger.info(
            "us_fetcher: batch %d/%d (%d tickers)",
            i // batch_size + 1,
            -(-len(tickers) // batch_size),
            len(batch),
        )
        try:
            raw = yf.download(
                batch,
                start=start,
                end=end,
                auto_adjust=True,
                group_by="ticker",
                threads=False,
                progress=False,
            )
        except Exception:
            logger.exception("us_fetcher: batch download failed: %s", batch[:3])
            continue
        if raw is None or raw.empty:
            logger.warning("us_fetcher: empty batch result: %s...", batch[:3])
            continue
        flat = _flatten_batch(raw, batch)
        if not flat.empty:
            frames.append(flat)
        if i + batch_size < len(tickers):
            time.sleep(sleep_sec)
    if not frames:
        logger.error("us_fetcher: ALL batches failed")
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True)
    logger.info(
        "us_fetcher: fetched %d rows for %d/%d tickers",
        len(result),
        result["ticker"].nunique(),
        len(tickers),
    )
    return result


def fetch_single_us(ticker: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Fetch one arbitrary US ticker (may be outside the universe; for /analyze)."""
    return fetch_us_ohlcv([ticker], start=start, end=end, batch_size=1, sleep_sec=0.0)
