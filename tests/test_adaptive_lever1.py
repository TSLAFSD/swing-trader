"""Adaptive Lever 1 tests: hardened circuit breaker + hysteresis + safeguard.

Also a regression test proving ADAPTIVE_LOOP_ENABLED=False falls back to the
legacy single-condition path (baseline behavior).
"""

import pandas as pd
import pytest

from config import settings
from src.backtest import tracker
from src.risk import circuit_breaker as cb


def fwd_df(specs: dict[str, list[float]]) -> pd.DataFrame:
    """Build a forward-returns frame: {strategy_id: [fwd_10d, ...]}."""
    rows = []
    for sid, rets in specs.items():
        for i, r in enumerate(rets):
            rows.append({"strategy_id": sid, "signal_date": f"2026-01-{i + 1:02d}", "fwd_10d": r})
    return pd.DataFrame(rows)


@pytest.fixture
def hardened(monkeypatch):
    monkeypatch.setattr(settings, "ADAPTIVE_LOOP_ENABLED", True)
    monkeypatch.setattr(settings, "CB_SUSPEND_TRAILING_N", 10)
    monkeypatch.setattr(settings, "CB_SUSPEND_RET_THRESHOLD", -0.02)
    monkeypatch.setattr(settings, "CB_SUSPEND_WINRATE_FLOOR", 0.40)
    monkeypatch.setattr(settings, "CB_REACTIVATE_RET_THRESHOLD", 0.0)


class TestTrailingStats:
    def test_stats(self) -> None:
        st = tracker.trailing_stats(fwd_df({"breakout": [0.05, -0.03, 0.02, -0.10, 0.01]}), "breakout", 10)
        assert st["n_realized"] == 5
        assert st["mean_fwd10"] == pytest.approx(-0.01)
        assert st["win_rate"] == pytest.approx(0.6)
        assert st["profit_factor"] == pytest.approx(0.08 / 0.13)

    def test_empty(self) -> None:
        st = tracker.trailing_stats(fwd_df({"breakout": []}), "breakout", 10)
        assert st["n_realized"] == 0 and st["win_rate"] is None


class TestHardenedSuspend:
    def test_suspend_low_mean_and_low_winrate(self, hardened) -> None:
        d = cb.evaluate_hardened(
            "breakout", fwd_df({"breakout": [-0.04] * 7 + [0.01] * 3}), currently_suspended=False
        )
        assert d.suspended is True  # mean -0.025 AND win rate 0.3

    def test_no_suspend_on_one_unlucky_window(self, hardened) -> None:
        # mean -0.021 (< -0.02) but 9/10 winners — must NOT suspend (the fix).
        d = cb.evaluate_hardened(
            "breakout", fwd_df({"breakout": [0.01] * 9 + [-0.30]}), currently_suspended=False
        )
        assert d.suspended is False

    def test_insufficient_sample_holds_state(self, hardened) -> None:
        thin = fwd_df({"breakout": [-0.04] * 3})  # 3 < 10 // 2
        assert cb.evaluate_hardened("breakout", thin, currently_suspended=False).suspended is False
        assert cb.evaluate_hardened("breakout", thin, currently_suspended=True).suspended is True


class TestHysteresis:
    def test_stays_suspended_between_thresholds(self, hardened) -> None:
        # mean -0.005: above suspend (-0.02) but below reactivate (0.0) -> stay.
        df = fwd_df({"breakout": [0.01] * 5 + [-0.02] * 5})
        assert cb.evaluate_hardened("breakout", df, currently_suspended=True).suspended is True

    def test_reactivates_when_clearing_higher_bar(self, hardened) -> None:
        df = fwd_df({"breakout": [0.02] * 8 + [-0.01] * 2})  # mean +0.014 >= 0.0
        assert cb.evaluate_hardened("breakout", df, currently_suspended=True).suspended is False


class TestSafeguard:
    def test_keeps_best_when_all_enabled_would_suspend(self, hardened, tmp_path) -> None:
        df = fwd_df({
            "breakout": [-0.04] * 7 + [0.01] * 3,  # mean -0.025
            "pullback": [-0.06] * 7 + [0.01] * 3,  # mean -0.039 (worse)
        })
        decisions = cb.update_all(
            df, ["breakout", "pullback"], enabled_ids={"breakout", "pullback"}, path=tmp_path / "cb.json"
        )
        states = {d.strategy_id: d for d in decisions}
        assert states["breakout"].suspended is False and states["breakout"].action == "safeguard_kept"
        assert states["pullback"].suspended is True

    def test_no_safeguard_when_one_survives(self, hardened, tmp_path) -> None:
        df = fwd_df({
            "breakout": [-0.04] * 7 + [0.01] * 3,  # suspend
            "pullback": [0.02] * 8 + [-0.01] * 2,  # healthy
        })
        decisions = cb.update_all(
            df, ["breakout", "pullback"], enabled_ids={"breakout", "pullback"}, path=tmp_path / "cb.json"
        )
        states = {d.strategy_id: d for d in decisions}
        assert states["breakout"].suspended is True
        assert states["pullback"].suspended is False


class TestRegressionFlagOff:
    def test_flag_off_uses_legacy_single_condition(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(settings, "ADAPTIVE_LOOP_ENABLED", False)
        monkeypatch.setattr(settings, "CB_TRAILING_SIGNALS", 10)
        monkeypatch.setattr(settings, "CB_MEAN_FWD10_MIN", -0.02)
        # Same one-unlucky-window input the hardened path spares — legacy suspends
        # it (no win-rate guard), proving flag-off = baseline behavior.
        df = fwd_df({"breakout": [0.01] * 9 + [-0.30]})
        decisions = cb.update_all(df, ["breakout"], path=tmp_path / "cb.json")
        assert decisions[0].suspended is True
        assert decisions[0].action == "none"  # legacy path sets no adaptive action
