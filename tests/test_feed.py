"""PWA feed (data/app/feed.json) tests — serialization, merge/prune, no-leak.

The feed must be NEUTRAL: it carries recommendation signals + the virtual paper
portfolio + system state, and never owner positions (§2 rule #4). It also has to
accumulate signals across scans (dedupe + prune) so one market's scan does not
wipe the other's.
"""

import json
from datetime import date, timedelta

from src.analysis.base_strategy import Signal
from src.report.feed import build_feed


def make_signal(
    ticker: str = "AAPL", market: str = "us", strategy_id: str = "breakout",
    strength: float = 80.0, price: float = 100.0, sd: date | None = None, grade: str = "A",
) -> Signal:
    return Signal(
        ticker=ticker, name=f"{ticker} Inc", market=market, strategy_id=strategy_id,
        direction="BUY", strength=strength, price=price, signal_date=sd or date.today(),
        suggested_stop_loss=95.0, suggested_take_profit=120.0, exit_mode="atr_trailing",
        reason="저점 재테스트", tags=["RS 상위 25%"], grade=grade, grade_value=78.0,
        confidence=0.7, regime_factor=0.9, entry_zone_top=102.0, wyckoff_badge="🟢 매집권",
        contrarian=["close<SMA200"],
    )


class TestBuildFeed:
    def test_structure_and_serialization(self, tmp_path) -> None:
        p = tmp_path / "feed.json"
        build_feed([make_signal()], {"AAPL": "https://x/r.html"}, path=p)
        feed = json.loads(p.read_text())
        assert set(feed) >= {"schema_version", "generated_at", "signals", "paper", "system"}
        assert len(feed["signals"]) == 1
        c = feed["signals"][0]
        assert c["ticker"] == "AAPL"
        assert c["grade"] == "A"
        assert c["price"] == 100.0
        assert c["entry_zone_top"] == 102.0
        assert c["report_url"] == "https://x/r.html"
        assert c["signal_date"] == date.today().isoformat()
        assert isinstance(feed["paper"], dict) and isinstance(feed["system"], dict)

    def test_missing_report_url_is_none(self, tmp_path) -> None:
        p = tmp_path / "feed.json"
        build_feed([make_signal()], {}, path=p)  # url map empty
        feed = json.loads(p.read_text())
        assert feed["signals"][0]["report_url"] is None

    def test_merge_dedup_and_prune(self, tmp_path) -> None:
        p = tmp_path / "feed.json"
        old = make_signal(ticker="OLD", sd=date.today() - timedelta(days=60))
        recent = make_signal(ticker="REC", sd=date.today() - timedelta(days=5))
        build_feed([old, recent], {}, path=p)

        new = make_signal(ticker="NEW", sd=date.today())
        dup = make_signal(ticker="REC", sd=date.today() - timedelta(days=5), strength=99.0)
        build_feed([new, dup], {}, path=p)

        feed = json.loads(p.read_text())
        tickers = {c["ticker"] for c in feed["signals"]}
        assert "OLD" not in tickers  # pruned (> FEED_RETENTION_DAYS)
        assert tickers == {"REC", "NEW"}
        rec = next(c for c in feed["signals"] if c["ticker"] == "REC")
        assert rec["strength"] == 99.0  # dedup: latest scan wins

    def test_no_owner_position_leak(self, tmp_path) -> None:
        p = tmp_path / "feed.json"
        build_feed([make_signal()], {"AAPL": "u"}, path=p)
        raw = p.read_text()
        # Fields unique to owner positions.yaml / closed_trades must never appear.
        for forbidden in ("quantity", "highest_close", "current_trailing_sl"):
            assert forbidden not in raw, f"owner-position field leaked: {forbidden}"

    def test_weekly_refresh_keeps_signals(self, tmp_path) -> None:
        p = tmp_path / "feed.json"
        build_feed([make_signal(ticker="KEEP")], {}, path=p)
        build_feed(path=p)  # weekly refresh: no signals passed
        feed = json.loads(p.read_text())
        assert {c["ticker"] for c in feed["signals"]} == {"KEEP"}
        assert "paper" in feed and "system" in feed
