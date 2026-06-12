"""U7 tests: trailing persistence, slot messaging, correlation tag in cards."""

from datetime import date

import pandas as pd
import pytest

from src.analysis.base_strategy import Signal
from src.notify.messages import _signal_card, holdings_summary
from src.risk.positions import Position, update_trailing_state


def make_frame(closes: list[float], atr: float = 2.0) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2026-05-01", periods=n).date,
            "open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
            "close": closes, "volume": 1000.0, "atr14": atr,
        }
    )


def make_position(**kw) -> Position:
    defaults = dict(
        ticker="TEST", market="us", entry_date=date(2026, 5, 1), entry_price=100.0,
        quantity=1.0, stop_loss=None, take_profit=None, exit_mode="atr_trailing",
    )
    defaults.update(kw)
    return Position(**defaults)


class TestTrailingPersistence:
    def test_initial_update_sets_state(self) -> None:
        pos = make_position()
        frames = {"TEST": make_frame([100, 104, 108, 106])}
        assert update_trailing_state([pos], frames) is True
        assert pos.highest_close == pytest.approx(108.0)
        assert pos.current_trailing_sl == pytest.approx(108.0 - 3 * 2.0)

    def test_no_change_no_commit(self) -> None:
        pos = make_position(highest_close=108.0, current_trailing_sl=102.0)
        frames = {"TEST": make_frame([100, 104, 108, 106])}
        assert update_trailing_state([pos], frames) is False  # same values -> no diff

    def test_never_regresses_on_restated_data(self) -> None:
        pos = make_position(highest_close=120.0, current_trailing_sl=114.0)
        frames = {"TEST": make_frame([100, 104, 108, 106])}  # data max only 108
        update_trailing_state([pos], frames)
        assert pos.highest_close == pytest.approx(120.0)  # persisted high kept

    def test_fixed_mode_untouched(self) -> None:
        pos = make_position(exit_mode="fixed")
        assert update_trailing_state([pos], {"TEST": make_frame([100, 110])}) is False
        assert pos.highest_close is None


class TestSlotMessaging:
    ROWS = [
        {"ticker": "AAPL", "name": "Apple", "market": "us", "entry_price": 280.0,
         "current": 291.58, "pnl_pct": 4.1, "near_stop": False},
        {"ticker": "005930", "name": "삼성전자", "market": "kr", "entry_price": 310000.0,
         "current": 299000.0, "pnl_pct": -3.5, "near_stop": True},
    ]

    def test_slot_header_and_hint(self) -> None:
        text = holdings_summary(self.ROWS, used_slots=2, max_slots=5, n_signals=4)
        assert "📊 2/5 슬롯" in text
        assert "남은 슬롯 3 — 오늘 시그널 중 TOP 3만 선별 권장" in text
        assert "⚠️손절근접" in text  # mixed profit + near-stop briefing

    def test_full_slots_no_hint(self) -> None:
        text = holdings_summary(self.ROWS, used_slots=5, max_slots=5, n_signals=4)
        assert "남은 슬롯" not in text


class TestCorrelationTagInCard:
    def test_warning_tag_reaches_send_text(self) -> None:
        sig = Signal(
            ticker="NVDA", name="NVIDIA", market="us", strategy_id="breakout",
            direction="BUY", strength=70.0, price=120.0, signal_date=date(2026, 6, 12),
            suggested_stop_loss=114.0, suggested_take_profit=None, exit_mode="atr_trailing",
            tags=["⚠️ 보유 중인 AMD과(와) 상관 높음 (60일 상관계수 0.85) — 분산 효과 낮음"],
            grade="B", wyckoff_badge="⚪ 해당 없음", entry_zone_top=121.5,
        )
        card = _signal_card(1, sig, "https://example.test/r.html")
        assert "상관 높음" in card and "분산 효과 낮음" in card
