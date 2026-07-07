"""Part 3 (2026-07-07): distribution badge on signal candidates — display only."""

from datetime import date

from src.analysis.base_strategy import Signal
from src.analysis.signal_engine import ScanResult
from src.notify import messages
from src.risk.distribution import DIST_TAG_PREFIX


def _sig(ticker: str, tags: list[str]) -> Signal:
    return Signal(
        ticker=ticker, name=ticker, market="us", strategy_id="breakout",
        direction="BUY", strength=70.0, price=100.0,
        signal_date=date(2026, 7, 7), tags=tags,
    )


def _result(signals: list[Signal]) -> ScanResult:
    return ScanResult(
        market="us", scan_date=date(2026, 7, 7), signals=signals,
        total_scanned=100,
    )


class TestDistributionBadgeInMessage:
    def test_health_line_counts_badged_signals(self) -> None:
        tagged = _sig("AAA", [f"{DIST_TAG_PREFIX} — 고점 돌파 후 거래량 3.0배"])
        clean = _sig("BBB", [])
        text = messages.scan_message(_result([tagged, clean]), {})
        assert "분산 의심 1건" in text
        assert f"   {DIST_TAG_PREFIX}" in text  # tag renders inside the card

    def test_no_count_when_no_badges(self) -> None:
        text = messages.scan_message(_result([_sig("AAA", [])]), {})
        assert "분산 의심" not in text
