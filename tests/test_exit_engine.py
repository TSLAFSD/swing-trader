"""Exit engine tests: every mode, hand-computed levels."""

import pytest

from src.risk.exit_engine import (
    DEFAULT_ROI_TABLE,
    PositionState,
    atr_trailing_stop,
    check_exit,
    roi_required,
)


def make_state(**kwargs) -> PositionState:
    defaults = dict(
        entry_price=100.0, current_close=100.0, highest_close_since_entry=100.0,
        days_held=1, atr=2.0, stop_loss=95.0, take_profit=115.0,
    )
    defaults.update(kwargs)
    return PositionState(**defaults)


class TestFixed:
    def test_stop_hit(self) -> None:
        assert check_exit("fixed", make_state(current_close=94.9)) is not None

    def test_target_hit(self) -> None:
        assert check_exit("fixed", make_state(current_close=115.1)) is not None

    def test_hold_between(self) -> None:
        assert check_exit("fixed", make_state(current_close=100.0)) is None


class TestAtrTrailing:
    def test_trailing_level_hand_computed(self) -> None:
        # highest 120, ATR 2, k=3 -> stop 114
        assert atr_trailing_stop(120.0, 2.0, 3.0) == pytest.approx(114.0)

    def test_trailing_hit(self) -> None:
        state = make_state(
            current_close=113.9, highest_close_since_entry=120.0, stop_loss=None, take_profit=None
        )
        assert check_exit("atr_trailing", state, atr_k=3.0) is not None

    def test_trailing_holds_above(self) -> None:
        state = make_state(
            current_close=114.1, highest_close_since_entry=120.0, stop_loss=None, take_profit=None
        )
        assert check_exit("atr_trailing", state, atr_k=3.0) is None

    def test_hard_stop_precedes_trailing(self) -> None:
        state = make_state(current_close=94.0, highest_close_since_entry=100.0, stop_loss=95.0)
        reason = check_exit("atr_trailing", state, atr_k=3.0)
        assert reason is not None and "손절" in reason

    def test_requires_atr(self) -> None:
        with pytest.raises(ValueError):
            check_exit("atr_trailing", make_state(atr=None))


class TestRoiTable:
    def test_ladder_lookup(self) -> None:
        assert roi_required(0, DEFAULT_ROI_TABLE) == pytest.approx(0.15)
        assert roi_required(4, DEFAULT_ROI_TABLE) == pytest.approx(0.15)
        assert roi_required(5, DEFAULT_ROI_TABLE) == pytest.approx(0.08)
        assert roi_required(12, DEFAULT_ROI_TABLE) == pytest.approx(0.03)

    def test_exit_when_ladder_met(self) -> None:
        # day 6: required 8%; +9% profit -> exit
        state = make_state(current_close=109.0, days_held=6, stop_loss=None, take_profit=None)
        assert check_exit("roi_table", state) is not None

    def test_hold_when_ladder_unmet(self) -> None:
        state = make_state(current_close=106.0, days_held=6, stop_loss=None, take_profit=None)
        assert check_exit("roi_table", state) is None


class TestTimeStops:
    def test_strategy_time_stop(self) -> None:
        state = make_state(current_close=101.0, days_held=10, stop_loss=None, take_profit=None)
        assert check_exit("fixed", state, time_stop_days=10) is not None

    def test_global_max_holding(self) -> None:
        state = make_state(current_close=101.0, days_held=20, stop_loss=None, take_profit=None)
        assert check_exit("fixed", state) is not None

    def test_unknown_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            check_exit("nope", make_state())
