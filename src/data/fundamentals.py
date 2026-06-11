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


def fetch_fundamentals(ticker: str, yf_symbol: str | None = None) -> Fundamentals:
    """Fetch a fundamentals snapshot; missing data yields None fields.

    Args:
        ticker: Canonical ticker (store key).
        yf_symbol: yfinance symbol if different (e.g. "005930.KS").

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

    return Fundamentals(
        ticker=ticker,
        per=grab("trailingPE"),
        pbr=grab("priceToBook"),
        market_cap=grab("marketCap"),
        dividend_yield=grab("dividendYield", "trailingAnnualDividendYield"),
        week52_high=grab("fiftyTwoWeekHigh"),
        week52_low=grab("fiftyTwoWeekLow"),
    )
