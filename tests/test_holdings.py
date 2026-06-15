"""Holdings add-on tests: yfinance news parser (both schemas) + Telegram block."""

from datetime import datetime, timedelta, timezone

import pytest

from src.data import news as news_mod
from src.data.news import NewsItem, fetch_us_news
from src.notify.messages import holdings_summary

UTC = timezone.utc


def _nested(title, days_ago=0, url="https://e/a", pub="Reuters"):
    """yfinance 1.4.x nested-`content` schema entry."""
    dt = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    return {
        "id": "x",
        "content": {
            "title": title,
            "provider": {"displayName": pub},
            "clickThroughUrl": {"url": url},
            "canonicalUrl": {"url": url + "-canon"},
            "pubDate": dt,
        },
    }


class TestParser:
    def test_nested_schema(self):
        item = news_mod._parse_item(_nested("Headline A"))
        assert item.title == "Headline A"
        assert item.publisher == "Reuters"
        assert item.link == "https://e/a"  # clickThroughUrl wins over canonical
        assert item.published_kst is not None and item.published_kst.utcoffset() == timedelta(hours=9)

    def test_old_top_level_schema(self):
        item = news_mod._parse_item(
            {"title": "Old", "link": "http://e/o", "publisher": "Wire", "providerPublishTime": 1765000000}
        )
        assert item.title == "Old" and item.publisher == "Wire" and item.link == "http://e/o"

    def test_malformed_and_missing_title(self):
        assert news_mod._parse_item({}) is None
        assert news_mod._parse_item({"content": {"provider": {"displayName": "x"}}}) is None
        assert news_mod._parse_item("not a dict") is None


class TestFetchFilterAndCap:
    def _patch(self, monkeypatch, raw_list):
        import yfinance as yf

        class FakeTicker:
            def __init__(self, *_a, **_k):
                self.news = raw_list

        monkeypatch.setattr(yf, "Ticker", FakeTicker)

    def test_recency_filter(self, monkeypatch):
        self._patch(monkeypatch, [_nested("fresh", 1), _nested("stale", 30), _nested("ok", 3)])
        titles = [i.title for i in fetch_us_news("AAPL", max_items=5, recency_days=7)]
        assert "stale" not in titles and "fresh" in titles and "ok" in titles

    def test_max_items_cap_and_order(self, monkeypatch):
        self._patch(monkeypatch, [_nested(f"n{d}", d) for d in (1, 2, 3, 4, 5)])
        items = fetch_us_news("AAPL", max_items=3, recency_days=10)
        assert [i.title for i in items] == ["n1", "n2", "n3"]  # newest first, capped

    def test_failure_returns_empty(self, monkeypatch):
        import yfinance as yf

        def boom(*_a, **_k):
            raise RuntimeError("network down")

        monkeypatch.setattr(yf, "Ticker", boom)
        assert fetch_us_news("AAPL") == []


class TestHoldingsMessage:
    BASE = {"name": "Apple", "ticker": "AAPL", "entry_price": 200.0, "current": 210.0, "pnl_pct": 5.0}

    def test_us_row_has_report_and_news(self):
        row = {**self.BASE, "market": "us", "report_url": "https://r/aapl.html",
               "news": [NewsItem("Big move", "Reuters", "https://n/1", None)]}
        msg = holdings_summary([row])
        assert "📄 상세 리포트: https://r/aapl.html" in msg
        assert "• Big move (Reuters) https://n/1" in msg

    def test_kr_row_has_report_no_news(self):
        row = {"name": "삼성", "ticker": "005930", "market": "kr", "entry_price": 70000.0,
               "current": 71000.0, "pnl_pct": 1.4, "report_url": "https://r/x.html"}
        msg = holdings_summary([row])
        assert "상세 리포트" in msg
        assert "뉴스" not in msg  # KR carries no news key at all

    def test_us_empty_news_line(self):
        row = {**self.BASE, "market": "us", "report_url": "https://r/a.html", "news": []}
        assert "• 최신 뉴스 없음" in holdings_summary([row])
