"""Adaptive Lever 3 tests: effective cutoff, bounded nudges, send_filter wiring."""

import json
from datetime import date

import pandas as pd
import pytest

from config import settings
from src.adaptive import cutoff
from src.analysis.base_strategy import Signal
from src.notify.send_filter import filter_for_send


def fwd_df(rows: list[tuple[float, float]]) -> pd.DataFrame:
    return pd.DataFrame([{"strength": s, "fwd_10d": r} for s, r in rows])


@pytest.fixture
def adaptive_on(monkeypatch):
    monkeypatch.setattr(settings, "ADAPTIVE_LOOP_ENABLED", True)
    monkeypatch.setattr(settings, "ACCEPTANCE_CUTOFF_ENABLED", True)
    monkeypatch.setattr(settings, "MIN_STRENGTH_SEND", 20.0)
    monkeypatch.setattr(settings, "ACCEPTANCE_CUTOFF_MAX_STEP", 5.0)
    monkeypatch.setattr(settings, "ACCEPTANCE_CUTOFF_FLOOR", 20.0)
    monkeypatch.setattr(settings, "ACCEPTANCE_CUTOFF_CEILING", 60.0)
    monkeypatch.setattr(settings, "ACCEPTANCE_MIN_SAMPLE", 10)


class TestEffectiveCutoff:
    def test_off_returns_baseline(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "ADAPTIVE_LOOP_ENABLED", False)
        monkeypatch.setattr(settings, "MIN_STRENGTH_SEND", 20.0)
        (tmp_path / "c.json").write_text(json.dumps({"cutoff": 55.0}))
        assert cutoff.effective_cutoff(tmp_path / "c.json") == 20.0

    def test_on_reads_state(self, adaptive_on, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"cutoff": 35.0}))
        assert cutoff.effective_cutoff(path) == 35.0

    def test_on_no_state_is_baseline(self, adaptive_on, tmp_path):
        assert cutoff.effective_cutoff(tmp_path / "missing.json") == 20.0


class TestProposeAndApply:
    def test_raise_when_accepted_band_loses(self, adaptive_on, tmp_path):
        path = tmp_path / "c.json"  # cutoff defaults to 20
        df = fwd_df([(25.0, -0.03)] * 8 + [(25.0, 0.01)] * 4)  # band [20,30): hit 33%, mean<0
        out = cutoff.propose_and_apply(df, path)
        assert out["changed"] is True and out["new"] == 25.0
        assert json.loads(path.read_text())["cutoff"] == 25.0

    def test_lower_when_rejected_band_wins(self, adaptive_on, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"cutoff": 40.0}))
        # accepted band [40,50) empty; rejected band [30,40) strongly positive
        df = fwd_df([(35.0, 0.03)] * 8 + [(35.0, -0.01)] * 4)  # hit 67%, mean>0
        out = cutoff.propose_and_apply(df, path)
        assert out["changed"] is True and out["new"] == 35.0

    def test_small_sample_no_change(self, adaptive_on, tmp_path):
        df = fwd_df([(25.0, -0.05)] * 5)  # 5 < min_sample 10
        out = cutoff.propose_and_apply(df, tmp_path / "c.json")
        assert out["changed"] is False and out["new"] == 20.0

    def test_raise_clamped_to_ceiling(self, adaptive_on, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"cutoff": 58.0}))
        df = fwd_df([(60.0, -0.04)] * 12)  # band [58,68): losing
        out = cutoff.propose_and_apply(df, path)
        assert out["new"] == 60.0  # 58 + 5 clamped to ceiling


class TestSendFilterWiring:
    def _sig(self, strength):
        return Signal(
            ticker="T", name="T", market="us", strategy_id="breakout", direction="BUY",
            strength=strength, price=100.0, signal_date=date(2026, 6, 15),
        )

    def test_off_uses_min_strength_send(self, monkeypatch):
        monkeypatch.setattr(settings, "ADAPTIVE_LOOP_ENABLED", False)
        monkeypatch.setattr(settings, "MIN_STRENGTH_SEND", 20.0)
        sendable, excluded = filter_for_send([self._sig(25.0), self._sig(15.0)], {})
        assert [s.strength for s in sendable] == [25.0]
        assert [d.signal.strength for d in excluded] == [15.0]
