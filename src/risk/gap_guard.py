"""US Gap Guard (spec §11.1): pre-market price re-check of the morning's signals.

Re-checks prices only — NEVER recomputes signals. No US signals that morning
= no message (this job is exempt from the health-check rule).
"""

import logging
from datetime import date

import pandas as pd

from config import settings
from src.backtest.tracker import load_signals

logger = logging.getLogger(__name__)


def _latest_price(ticker: str) -> float | None:
    """Best-available current quote (pre/post market when exposed)."""
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).fast_info
        for attr in ("pre_market_price", "post_market_price", "last_price"):
            value = getattr(info, attr, None)
            if value:
                return float(value)
    except Exception:
        logger.exception("gap guard: quote failed for %s", ticker)
    return None


def check_us_gaps(today: date | None = None) -> list[dict]:
    """Compare this morning's US BUY signals against current quotes.

    Returns:
        Items for messages.gap_guard_message(); empty list = send nothing.
    """
    today = today or date.today()
    signals = load_signals()
    if signals.empty:
        return []
    todays = signals[
        (signals["market"] == "us")
        & (pd.to_datetime(signals["signal_date"]).dt.date >= today)
    ]
    # The us-close scan stamps the previous US trading day's date; also accept
    # signals logged within the last calendar day.
    if todays.empty:
        recent_cut = pd.Timestamp(today) - pd.Timedelta(days=1)
        todays = signals[
            (signals["market"] == "us")
            & (pd.to_datetime(signals["signal_date"]) >= recent_cut)
        ]
    items: list[dict] = []
    threshold = settings.GAP_ALERT_PCT
    for _, row in todays.iterrows():
        current = _latest_price(row["ticker"])
        if current is None:
            continue
        sig_price = float(row["price"])
        gap = (current / sig_price - 1) * 100
        item = {
            "ticker": row["ticker"],
            "signal_price": sig_price,
            "current_price": current,
            "gap_pct": gap,
            "threshold": threshold,
        }
        if gap >= threshold:
            # Recalculate stop/target FROM THE CURRENT PRICE (spec §11.1):
            # keep the signal's risk distances, re-anchored to the live quote.
            ratio = current / sig_price
            stop = row.get("stop_loss")
            target = row.get("take_profit")
            item["new_stop"] = round(float(stop) * ratio, 2) if pd.notna(stop) else round(current * 0.95, 2)
            item["new_target"] = round(float(target) * ratio, 2) if pd.notna(target) else None
        items.append(item)
    return items
