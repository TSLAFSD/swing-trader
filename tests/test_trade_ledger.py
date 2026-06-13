"""Closed-trade ledger: record/load roundtrip, discipline summary, /remove hook."""

from datetime import date

import pandas as pd
import yaml

from config import settings
from src.commands import positions_cmd
from src.risk import trade_ledger


def _record(**kw) -> dict:
    base = dict(
        ticker="AAPL", market="us", entry_date="2026-06-01", entry_price=100.0,
        quantity=10.0, stop_loss=95.0, take_profit=None, exit_mode="atr_trailing",
        exit_date="2026-06-12", exit_price=110.0, exit_price_source="provided",
        return_pct=10.0, holding_days=11, exit_reason="manual_remove",
    )
    base.update(kw)
    return base


class TestLedgerStorage:
    def test_record_and_load_roundtrip(self, tmp_path) -> None:
        path = tmp_path / "closed_trades.parquet"
        assert trade_ledger.record_closed_trade(_record(), path=path) == 1
        assert trade_ledger.record_closed_trade(_record(ticker="MSFT"), path=path) == 2
        df = trade_ledger.load_closed_trades(path=path)
        assert list(df["ticker"]) == ["AAPL", "MSFT"]
        assert set(trade_ledger.COLUMNS) <= set(df.columns)

    def test_load_missing_is_empty(self, tmp_path) -> None:
        assert trade_ledger.load_closed_trades(path=tmp_path / "nope.parquet").empty


class TestDisciplineSummary:
    def test_empty(self) -> None:
        empty = pd.DataFrame(columns=trade_ledger.COLUMNS)
        assert "아직 기록된 청산이 없습니다" in trade_ledger.discipline_summary_kr(empty)

    def test_mixed_wins_losses(self) -> None:
        df = pd.DataFrame(
            [
                _record(return_pct=12.0),
                _record(return_pct=8.0),
                _record(return_pct=-4.0),
            ]
        )
        text = trade_ledger.discipline_summary_kr(df)
        assert "청산 3건" in text
        assert "승률 67%" in text  # 2 of 3
        # PF = (12+8) / 4 = 5.00
        assert "Profit Factor 5.00" in text

    def test_estimated_flag_surfaced(self) -> None:
        df = pd.DataFrame([_record(exit_price_source="estimated_close")])
        assert "청산가 추정" in trade_ledger.discipline_summary_kr(df)


class TestRemovePositionRecordsExit:
    def _setup(self, tmp_path, monkeypatch, position: dict):
        pos_file = tmp_path / "positions.yaml"
        pos_file.write_text(yaml.safe_dump({"positions": [position]}), encoding="utf-8")
        ledger = tmp_path / "trades" / "closed_trades.parquet"
        monkeypatch.setattr(settings, "POSITIONS_FILE", pos_file)
        monkeypatch.setattr(positions_cmd, "REBUY_STATE_FILE", tmp_path / "state" / "rebuy.json")
        monkeypatch.setattr(trade_ledger, "CLOSED_TRADES_FILE", ledger)
        sent: list[str] = []
        monkeypatch.setattr(positions_cmd, "send_message", lambda m: sent.append(m))
        return ledger, sent

    def test_explicit_price_recorded(self, tmp_path, monkeypatch) -> None:
        pos = dict(ticker="AAPL", market="us", entry_date="2026-06-01",
                   entry_price=100.0, quantity=10.0, stop_loss=95.0,
                   take_profit=None, exit_mode="atr_trailing")
        ledger, sent = self._setup(tmp_path, monkeypatch, pos)
        positions_cmd.remove_position("AAPL", 95.0)  # -5%
        df = trade_ledger.load_closed_trades(path=ledger)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["exit_price"] == 95.0
        assert row["exit_price_source"] == "provided"
        assert row["return_pct"] == -5.0
        assert "실현 -5.0%" in sent[-1]

    def test_estimated_price_when_omitted(self, tmp_path, monkeypatch) -> None:
        pos = dict(ticker="AAPL", market="us", entry_date="2026-06-01",
                   entry_price=100.0, quantity=10.0, stop_loss=95.0,
                   take_profit=None, exit_mode="fixed")
        ledger, sent = self._setup(tmp_path, monkeypatch, pos)
        monkeypatch.setattr(positions_cmd, "_latest_close", lambda t, m: 110.0)
        positions_cmd.remove_position("AAPL")  # +10%, estimated
        row = trade_ledger.load_closed_trades(path=ledger).iloc[0]
        assert row["exit_price_source"] == "estimated_close"
        assert row["return_pct"] == 10.0
        assert "추정가" in sent[-1]

    def test_unknown_ticker_no_record(self, tmp_path, monkeypatch) -> None:
        pos = dict(ticker="AAPL", market="us", entry_date="2026-06-01",
                   entry_price=100.0, quantity=10.0, stop_loss=95.0,
                   take_profit=None, exit_mode="fixed")
        ledger, sent = self._setup(tmp_path, monkeypatch, pos)
        positions_cmd.remove_position("TSLA")
        assert trade_ledger.load_closed_trades(path=ledger).empty
        assert "보유 목록에 없습니다" in sent[-1]
