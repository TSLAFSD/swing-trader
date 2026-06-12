"""Best-effort fundamentals via yfinance .info.

Failed fields are None; a total failure returns an all-None block.
This module must NEVER raise into the pipeline.
"""

import logging
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)


@dataclass
class Fundamentals:
    """Fundamental snapshot; every field is best-effort and may be None."""

    ticker: str
    per: float | None = None  # trailing P/E
    pbr: float | None = None  # price-to-book
    market_cap: float | None = None
    dividend_yield: float | None = None  # fraction, e.g. 0.015
    week52_high: float | None = None
    week52_low: float | None = None

    def as_dict(self) -> dict[str, float | str | None]:
        """Return a plain dict (for templates/serialization)."""
        return asdict(self)


def fetch_fundamentals(ticker: str, yf_symbol: str | None = None, market: str = "us") -> Fundamentals:
    """Fetch a fundamentals snapshot; missing data yields None fields.

    Args:
        ticker: Canonical ticker (store key).
        yf_symbol: yfinance symbol if different (e.g. "005930.KS").
        market: "us" | "kr" — kr enables the pykrx best-effort supplement.

    Returns:
        Fundamentals with None for anything unavailable.
    """
    symbol = yf_symbol or ticker
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
    except Exception:
        logger.exception("fundamentals: .info failed for %s — returning empty block", symbol)
        return Fundamentals(ticker=ticker)

    def grab(*keys: str) -> float | None:
        for key in keys:
            value = info.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    fund = Fundamentals(
        ticker=ticker,
        per=grab("trailingPE"),
        pbr=grab("priceToBook"),
        market_cap=grab("marketCap"),
        dividend_yield=grab("dividendYield", "trailingAnnualDividendYield"),
        week52_high=grab("fiftyTwoWeekHigh"),
        week52_low=grab("fiftyTwoWeekLow"),
    )
    # KR supplement (A-1): yfinance valuation fields are usually empty for
    # KRX tickers — fill PER/PBR/배당 from pykrx, best-effort, never blocks.
    # NOTE (2026-06-12): KRX currently serves non-JSON to the fundamental
    # endpoint (login-gated) — this path is kept for if/when it unblocks;
    # pykrx's internal error print is silenced via redirect.
    if market == "kr" and (fund.per is None or fund.pbr is None or fund.dividend_yield is None):
        try:
            import contextlib
            import io
            from datetime import date, timedelta

            from pykrx import stock

            end = date.today()
            with contextlib.redirect_stdout(io.StringIO()):
                df = stock.get_market_fundamental(
                    (end - timedelta(days=10)).strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker
                )
            if df is not None and not df.empty:
                row = df.iloc[-1]
                if fund.per is None and row.get("PER", 0) > 0:
                    fund.per = float(row["PER"])
                if fund.pbr is None and row.get("PBR", 0) > 0:
                    fund.pbr = float(row["PBR"])
                if fund.dividend_yield is None and row.get("DIV", 0) > 0:
                    fund.dividend_yield = float(row["DIV"])
        except Exception:
            logger.debug("fundamentals: pykrx supplement failed for %s (best-effort)", ticker, exc_info=True)
    # KR market cap fallback via FDR KRX listing (Marcap, KRW).
    if market == "kr" and fund.market_cap is None:
        try:
            import FinanceDataReader as fdr

            listing = fdr.StockListing("KRX")
            row = listing[listing["Code"].astype(str).str.zfill(6) == ticker]
            if not row.empty and float(row["Marcap"].iloc[0]) > 0:
                fund.market_cap = float(row["Marcap"].iloc[0])
        except Exception:
            logger.debug("fundamentals: FDR marcap fallback failed for %s", ticker, exc_info=True)
    return fund
