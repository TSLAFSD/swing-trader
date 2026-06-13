"""P-A tests: virtual portfolio open/exit cycle + signals.parquet enrichment.

The exit decision goes through the real positions.evaluate_position ->
exit_engine.check_exit path (parity with the live monitor), exercised against
a real ParquetStore so the test covers the actual integration, not a mock.
"""

import json
from datetime import date

import pandas as pd
import pytest

from config import settings
from src.analysis.base_strategy import Signal
from src.backtest import tracker
from src.data.store import ParquetStore
from src.paper import portfolio


def make_ohlcv(ticker: str, closes: list[float], start: str = "2026-01-05") -> pd.DataFrame:
    """Synthetic long-format OHLCV with the store's canonical columns."""
    n = len(closes)
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": pd.bdate_range(start, periods=n).date,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": 1_000_000.0,
            "source": "test",
        }
    )


def make_signal(ticker="TST", market="us", price=100.0, grade="A", **kw) -> Signal:
    last_date = kw.pop("signal_date", date(2026, 3, 27))
    defaults = dict(
        ticker=ticker, name=ticker, market=market, strategy_id="breakout",
        direction="BUY", strength=72.0, price=price, signal_date=last_date,
        indicators={"rsi14": 55.0, "atr14": 2.0}, suggested_stop_loss=95.0,
        suggested_take_profit=120.0, exit_mode="fixed", grade=grade,
        grade_value=82.0, confidence=0.6, regime_factor=1.0,
    )
    defaults.update(kw)
    return Signal(**defaults)


@pytest.fixture
def paths(tmp_path):
    return {
        "store": ParquetStore(root=tmp_path / "data"),
        "open": tmp_path / "paper" / "open.json",
        "trades": tmp_path / "paper" / "trades.parquet",
    }


class TestOpenExitCycle:
    def test_open_then_stop_exit(self, paths) -> None:
        store = paths["store"]
        # 60 flat bars ending at 100; signal_date = last bar date.
        closes = [100.0] * 60
        df = make_ohlcv("TST", closes)
        store.upsert(df, "us")
        last_date = df["date"].iloc[-1]
        sig = make_signal(signal_date=last_date, price=100.0)

        out = portfolio.update_paper_portfolio(
            "us", [sig], store, open_path=paths["open"], trades_path=paths["trades"]
        )
        assert out["n_opened"] == 1
        assert out["open_total"] == 1
        assert out["closed"] == []
        open_rows = json.loads(paths["open"].read_text())
        assert len(open_rows) == 1
        held = open_rows[0]
        assert held["ticker"] == "TST"
        assert held["entry_fill"] > held["entry_price"]  # buy-side slippage applied
        assert held["features"]["rsi14"] == 55.0  # entry-time snapshot persisted

        # Next bar drops below the 95 stop -> exit on the second scan.
        drop = make_ohlcv("TST", [90.0], start="2026-03-30")  # one bday after last
        store.upsert(drop, "us")
        out2 = portfolio.update_paper_portfolio(
            "us", [], store, open_path=paths["open"], trades_path=paths["trades"]
        )
        assert out2["n_opened"] == 0
        assert out2["open_total"] == 0
        assert len(out2["closed"]) == 1
        rec = out2["closed"][0]
        assert rec["exit_reason"] == "stop"
        assert rec["return_pct"] < 0
        assert rec["return_pct"] == pytest.approx(-10.0, abs=0.5)
        assert rec["mae_pct"] < 0
        assert json.loads(paths["open"].read_text()) == []
        # Ledger persisted and self-contained (features + outcome in one row).
        trades = portfolio.load_trades(paths["trades"])
        assert len(trades) == 1
        assert set(["return_pct", "features_json", "grade", "mae_pct"]).issubset(trades.columns)

    def test_take_profit_exit(self, paths) -> None:
        store = paths["store"]
        df = make_ohlcv("TST", [100.0] * 30)
        store.upsert(df, "us")
        sig = make_signal(signal_date=df["date"].iloc[-1])
        portfolio.update_paper_portfolio(
            "us", [sig], store, open_path=paths["open"], trades_path=paths["trades"]
        )
        store.upsert(make_ohlcv("TST", [125.0], start="2026-02-16"), "us")
        out = portfolio.update_paper_portfolio(
            "us", [], store, open_path=paths["open"], trades_path=paths["trades"]
        )
        assert out["closed"][0]["exit_reason"] == "take_profit"
        assert out["closed"][0]["return_pct"] > 0


class TestEntryRules:
    def test_only_a_grade_enters(self, paths) -> None:
        out = portfolio.update_paper_portfolio(
            "us", [make_signal(grade="B")], paths["store"],
            open_path=paths["open"], trades_path=paths["trades"],
        )
        assert out["n_opened"] == 0
        assert out["open_total"] == 0

    def test_no_duplicate_entry(self, paths) -> None:
        existing = [{"ticker": "TST", "market": "us", "entry_date": "2026-03-27"}]
        paths["open"].parent.mkdir(parents=True, exist_ok=True)
        paths["open"].write_text(json.dumps(existing))
        out = portfolio.update_paper_portfolio(
            "us", [make_signal(ticker="TST")], paths["store"],
            open_path=paths["open"], trades_path=paths["trades"],
        )
        assert out["n_opened"] == 0  # already held (empty store -> survives untouched)
        assert out["open_total"] == 1

    def test_slot_cap_blocks_entry(self, paths) -> None:
        full = [
            {"ticker": f"H{i}", "market": "us", "entry_date": "2026-03-27"}
            for i in range(settings.MAX_POSITION_SLOTS)
        ]
        paths["open"].parent.mkdir(parents=True, exist_ok=True)
        paths["open"].write_text(json.dumps(full))
        out = portfolio.update_paper_portfolio(
            "us", [make_signal(ticker="NEW")], paths["store"],
            open_path=paths["open"], trades_path=paths["trades"],
        )
        assert out["n_opened"] == 0
        assert out["open_total"] == settings.MAX_POSITION_SLOTS


class TestSignalEnrichment:
    def test_record_signals_writes_enrichment_columns(self, tmp_path) -> None:
        path = tmp_path / "signals.parquet"
        sig = make_signal()
        sig.indicators = {"rsi14": 55.0, "atr14": 2.0, "bad": float("nan")}
        tracker.record_signals([sig], path=path)
        df = pd.read_parquet(path)
        row = df.iloc[0]
        assert row["grade"] == "A"
        assert row["grade_value"] == 82.0
        assert row["confidence"] == 0.6
        assert row["regime_factor"] == 1.0
        feats = json.loads(row["features_json"])
        assert feats["rsi14"] == 55.0
        assert feats["bad"] is None  # non-finite preserved as null, not dropped
