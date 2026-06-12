"""Send-stage cutoff tests (U1/A-2) — each gate exercised independently."""

from datetime import date

import pytest

from config import settings
from src.analysis.base_strategy import Signal
from src.backtest.confidence import ConfidenceReport
from src.notify.send_filter import filter_for_send, stop_width_pct


def make_signal(strength: float = 50.0, price: float = 100.0, stop: float | None = 95.0) -> Signal:
    return Signal(
        ticker="TEST", name="테스트", market="us", strategy_id="breakout",
        direction="BUY", strength=strength, price=price, signal_date=date(2026, 6, 12),
        suggested_stop_loss=stop, suggested_take_profit=None, exit_mode="fixed",
    )


def make_conf(n: int = 20, pf: float = 1.5, wr: float = 0.55) -> ConfidenceReport:
    return ConfidenceReport(
        ticker="TEST", strategy_id="breakout", n_trades=n, win_rate=wr,
        profit_factor=pf, avg_holding_days=5.0, max_drawdown_pct=10.0,
        score=0.6, label_kr="-",
    )


class TestSendFilter:
    def test_clean_signal_passes(self) -> None:
        send, excluded = filter_for_send([make_signal()], {"TEST": make_conf()})
        assert len(send) == 1 and not excluded

    def test_low_pf_excluded(self) -> None:
        send, excluded = filter_for_send([make_signal()], {"TEST": make_conf(pf=0.8)})
        assert not send and "PF" in excluded[0].reasons[0]

    def test_low_sample_excluded(self) -> None:
        send, excluded = filter_for_send([make_signal()], {"TEST": make_conf(n=3)})
        assert not send and "표본" in excluded[0].reasons[0]

    def test_low_strength_excluded(self) -> None:
        send, excluded = filter_for_send([make_signal(strength=15.0)], {"TEST": make_conf()})
        assert not send and "강도" in excluded[0].reasons[0]

    def test_wide_stop_dropped_by_default(self) -> None:
        # stop 32% below entry (the real 131290 case) -> dropped
        assert settings.STOP_TOO_WIDE_MODE == "drop"
        send, excluded = filter_for_send(
            [make_signal(price=100.0, stop=68.0)], {"TEST": make_conf()}
        )
        assert not send and "손절폭" in excluded[0].reasons[0]

    def test_wide_stop_tag_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "STOP_TOO_WIDE_MODE", "tag")
        sig = make_signal(price=100.0, stop=68.0)
        send, excluded = filter_for_send([sig], {"TEST": make_conf()})
        assert len(send) == 1 and not excluded
        assert any("손절폭 과대" in t for t in sig.tags)

    def test_inf_pf_passes(self) -> None:
        send, _ = filter_for_send([make_signal()], {"TEST": make_conf(pf=float("inf"))})
        assert len(send) == 1

    def test_stop_width_hand_computed(self) -> None:
        assert stop_width_pct(make_signal(price=100.0, stop=85.0)) == pytest.approx(15.0)
        assert stop_width_pct(make_signal(stop=None)) is None
