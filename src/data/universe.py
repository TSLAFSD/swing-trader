"""Universe loaders.

US: Russell 1000 — iShares IWB holdings CSV (primary), Wikipedia (fallback),
    committed cache CSV (last resort; a refresh failure must never kill a scan).
KR: KOSPI + KOSDAQ via FinanceDataReader, excluding 관리종목/거래정지.

Price/volume pre-scan filters are applied later, after OHLCV is available.
"""

import io
import logging
from pathlib import Path

import pandas as pd
import requests

from config import settings

logger = logging.getLogger(__name__)

_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (swing-trader pipeline)"}


def _russell1000_from_ishares() -> pd.DataFrame:
    """Parse the iShares IWB holdings CSV into [ticker, name]."""
    resp = requests.get(settings.ISHARES_IWB_CSV_URL, headers=_REQUEST_HEADERS, timeout=30)
    resp.raise_for_status()
    lines = resp.text.splitlines()
    header_idx = next(i for i, line in enumerate(lines) if line.startswith("Ticker"))
    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
    df = df[df["Asset Class"] == "Equity"][["Ticker", "Name"]].dropna()
    df.columns = ["ticker", "name"]
    df["ticker"] = df["ticker"].str.strip().str.replace(".", "-", regex=False)
    df = df[df["ticker"].str.fullmatch(r"[A-Z\-]+")]
    return df.drop_duplicates("ticker").reset_index(drop=True)


def _russell1000_from_wikipedia() -> pd.DataFrame:
    """Parse the Russell 1000 components table from Wikipedia into [ticker, name]."""
    resp = requests.get(settings.RUSSELL1000_WIKI_URL, headers=_REQUEST_HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    components = next(
        t for t in tables
        if {"Symbol", "Company"}.issubset(set(map(str, t.columns)))
        or {"Ticker", "Company"}.issubset(set(map(str, t.columns)))
    )
    symbol_col = "Symbol" if "Symbol" in components.columns else "Ticker"
    df = components[[symbol_col, "Company"]].dropna()
    df.columns = ["ticker", "name"]
    df["ticker"] = df["ticker"].str.strip().str.replace(".", "-", regex=False)
    return df.drop_duplicates("ticker").reset_index(drop=True)


def load_us_universe(refresh: bool = True) -> pd.DataFrame:
    """Load the Russell 1000 universe with cached fallback.

    On a successful refresh the cache file is rewritten; on total failure the
    cached list is served so a refresh failure never kills a scan.

    Args:
        refresh: If False, serve the cache directly (weekly job re-validates).

    Returns:
        DataFrame[ticker, name].

    Raises:
        RuntimeError: If refresh fails AND no cache exists.
    """
    cache: Path = settings.RUSSELL1000_CACHE_FILE
    if refresh:
        for source_name, loader in [
            ("ishares", _russell1000_from_ishares),
            ("wikipedia", _russell1000_from_wikipedia),
        ]:
            try:
                df = loader()
                if len(df) < 800:  # sanity: Russell 1000 should be ~1000 names
                    raise ValueError(f"only {len(df)} tickers parsed — refusing")
                cache.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(cache, index=False)
                logger.info("us universe: %d tickers from %s (cache updated)", len(df), source_name)
                return df
            except Exception:
                logger.exception("us universe: %s source failed", source_name)
    if cache.exists():
        df = pd.read_csv(cache, dtype={"ticker": str})
        logger.warning("us universe: serving CACHED list (%d tickers)", len(df))
        return df
    raise RuntimeError("US universe refresh failed and no cache exists")


def load_kr_universe() -> pd.DataFrame:
    """Load KOSPI + KOSDAQ listings, excluding 관리종목/거래정지.

    Returns:
        DataFrame[ticker, name, market] where market is KOSPI or KOSDAQ.
    """
    import FinanceDataReader as fdr

    frames = []
    for market in ("KOSPI", "KOSDAQ"):
        listing = fdr.StockListing(market)
        listing = listing.rename(columns={"Code": "ticker", "Name": "name"})
        listing["market"] = market
        frames.append(listing[["ticker", "name", "market"]])
    universe = pd.concat(frames, ignore_index=True)
    universe["ticker"] = universe["ticker"].astype(str).str.zfill(6)

    # 관리종목 exclusion. 거래정지 has no dedicated listing — halted tickers are
    # dropped later by the data-level "has a bar on the latest trading day" filter.
    excluded: set[str] = set()
    try:
        admin = fdr.StockListing("KRX-ADMINISTRATIVE")
        excluded = set(admin["Symbol"].astype(str).str.zfill(6))
        logger.info("kr universe: %d 관리종목 to exclude", len(excluded))
    except Exception:
        logger.exception("kr universe: 관리종목 list unavailable — continuing without it")
    before = len(universe)
    universe = universe[~universe["ticker"].isin(excluded)].reset_index(drop=True)
    logger.info("kr universe: %d tickers (%d excluded)", len(universe), before - len(universe))
    return universe
