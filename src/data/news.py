"""US-holdings news (headlines + links only) via yfinance — best-effort.

yfinance's Ticker.news schema is version-dependent. Installed 1.4.1 nests fields
under a `content` object: title / provider.displayName / clickThroughUrl.url
(or canonicalUrl.url) / pubDate (ISO-8601). Older releases exposed top-level
title / link / publisher / providerPublishTime. This parser handles BOTH and
NEVER raises — any failure or malformed entry yields [] / is skipped, so a scan
is never broken by news.

US tickers only (KR coverage is unreliable — owner decision). Headlines + links
only: no scraping, no summarization, no new dependencies, no API keys.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


@dataclass
class NewsItem:
    """One news headline with its source link (no article body, no summary)."""

    title: str
    publisher: str | None
    link: str
    published_kst: datetime | None


def _parse_dt(value) -> datetime | None:
    """Epoch seconds or ISO-8601 string -> KST datetime; None on any failure."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST)
    except (ValueError, OverflowError, OSError):
        return None


def _parse_item(raw: dict) -> NewsItem | None:
    """Map one yfinance news entry (either schema) to a NewsItem, or None."""
    if not isinstance(raw, dict):
        return None
    content = raw["content"] if isinstance(raw.get("content"), dict) else raw
    title = content.get("title") or raw.get("title")
    if not title:
        return None
    link = ""
    for key in ("clickThroughUrl", "canonicalUrl"):  # new schema: nested {url}
        node = content.get(key)
        if isinstance(node, dict) and node.get("url"):
            link = node["url"]
            break
    if not link:  # old schema: top-level link
        link = content.get("link") or raw.get("link") or ""
    provider = content.get("provider")
    if isinstance(provider, dict):
        publisher = provider.get("displayName")
    else:
        publisher = content.get("publisher") or raw.get("publisher")
    published = _parse_dt(
        content.get("pubDate") or content.get("displayTime") or raw.get("providerPublishTime")
    )
    return NewsItem(title=str(title), publisher=publisher, link=str(link), published_kst=published)


def fetch_us_news(ticker: str, max_items: int = 3, recency_days: int = 7) -> list[NewsItem]:
    """Recent US-ticker news, newest-first, capped at max_items.

    Best-effort: returns [] on ANY error (never raises, never blocks a scan).
    Items older than recency_days are dropped; undated items are kept (ranked
    last) rather than silently discarded.
    """
    try:
        import yfinance as yf

        raw_list = yf.Ticker(ticker).news or []
    except Exception:
        logger.warning("news: fetch failed for %s", ticker, exc_info=True)
        return []
    items: list[NewsItem] = []
    for raw in raw_list:
        try:
            item = _parse_item(raw)
        except Exception:
            logger.warning("news: parse failed for one %s item", ticker, exc_info=True)
            item = None
        if item:
            items.append(item)
    cutoff = datetime.now(KST) - timedelta(days=recency_days)
    fresh = [i for i in items if i.published_kst is None or i.published_kst >= cutoff]
    fresh.sort(key=lambda i: i.published_kst or datetime.min.replace(tzinfo=KST), reverse=True)
    return fresh[:max_items]
