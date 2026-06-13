"""P-B tests: paper stats, dashboard render, weekly summary, top-pick crown."""

from datetime import date

import pandas as pd
import pytest

from src.analysis.base_strategy import Signal
from src.analysis.signal_engine import ScanResult
from src.notify.messages import scan_message
from src.paper import stats
from src.paper.portfolio import TRADES_COLUMNS
from src.report import paper_report


def make_trades() -> pd.DataFrame:
    """3 closed virtual trades: +10%, +5%, -8% (cash 2000 each)."""
    base = {c: None for c in TRADES_COLUMNS}
    specs = [("AAA", 10.0, 12), ("BBB", 5.0, 6), ("CCC", -8.0, 9)]
    rows = []
    for i, (ticker, ret, hold) in enumerate(specs):
        row = dict(base)
        row.update(
            trade_id=f"id{i}", ticker=ticker, market="us", strategy_id="breakout",
            grade="A", grade_value=80.0, signal_date="2026-01-05", entry_date="2026-01-05",
            exit_date=f"2026-01-{10 + i:02d}", entry_price=100.0, entry_fill=100.05,
            shares=20.0, cash_allocated=2000.0, exit_mode="fixed", entry_rule="close",
            exit_reason="take_profit" if ret > 0 else "stop", holding_days=hold,
            return_pct=ret, pnl=2000.0 * ret / 100.0, mae_pct=-3.0, mfe_pct=ret + 2,
            features_json="{}", rationale_kr="A등급 추천", exit_rationale_kr="x", schema_version=1,
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=TRADES_COLUMNS)


class TestSummarize:
    def test_metrics(self) -> None:
        s = stats.summarize(make_trades(), [], start_equity=10_000.0)
        assert s["n_closed"] == 3
        assert s["win_rate"] == pytest.approx(2 / 3)
        assert s["profit_factor"] == pytest.approx(15 / 8)  # (10+5)/8
        assert s["realized_pnl"] == pytest.approx(140.0)  # 2000*(0.10+0.05-0.08)
        assert s["total_return_pct"] == pytest.approx(1.4)
        assert s["best"]["ticker"] == "AAA"
        assert s["worst"]["ticker"] == "CCC"
        assert s["max_drawdown_pct"] < 0  # dipped after the losing trade
        assert s["period_start"] == date(2026, 1, 5)

    def test_empty(self) -> None:
        s = stats.summarize(pd.DataFrame(columns=TRADES_COLUMNS), [])
        assert s["n_closed"] == 0
        assert s["total_return_pct"] == 0.0


class TestEquityCurve:
    def test_final_equity(self) -> None:
        curve = stats.equity_curve(make_trades(), 10_000.0)
        assert len(curve) == 3
        assert curve["equity"].iloc[-1] == pytest.approx(10_140.0)


class TestSummaryKr:
    def test_text(self) -> None:
        txt = stats.summary_kr(make_trades(), [], benchmark_pct=0.5, url="http://x/paper.html")
        assert "가상 포트폴리오 성과" in txt
        assert "초과수익" in txt
        assert "paper.html" in txt

    def test_empty(self) -> None:
        assert "아직 거래가 없습니다" in stats.summary_kr(pd.DataFrame(columns=TRADES_COLUMNS), [])


class TestPaperReport:
    def test_render(self, tmp_path) -> None:
        path = paper_report.build_paper_report(make_trades(), [], benchmark_pct=0.5, out_dir=tmp_path)
        assert path.name == "paper.html"
        html = path.read_text(encoding="utf-8")
        assert "가상 포트폴리오" in html
        assert "AAA" in html  # appears in the recent-trades table
        assert "과거 성과가 미래" in html  # disclaimer present

    def test_render_empty(self, tmp_path) -> None:
        path = paper_report.build_paper_report(pd.DataFrame(columns=TRADES_COLUMNS), [], out_dir=tmp_path)
        html = path.read_text(encoding="utf-8")
        assert "아직 청산된 가상 거래가 없습니다" in html


class TestTopPick:
    def test_crown_in_scan_message(self) -> None:
        sig = Signal(
            ticker="NVDA", name="엔비디아", market="us", strategy_id="breakout",
            direction="BUY", strength=80.0, price=120.0, signal_date=date(2026, 6, 12),
            grade="A",
        )
        res = ScanResult(market="us", scan_date=date(2026, 6, 12), signals=[sig], total_scanned=1000)
        msg = scan_message(res, {}, {})
        assert "🏆 오늘의 최우선 추천: 엔비디아(NVDA)" in msg
        assert "등급 A" in msg
