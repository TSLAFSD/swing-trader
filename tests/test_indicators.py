"""Indicator tests against hand-computed values on simple series."""

import math

import numpy as np
import pandas as pd
import pytest

from src.analysis.indicators import (
    breadth_pct,
    compute_indicators,
    rs_composite,
    rs_momentum_percentile,
)


def make_ohlcv(closes: list[float], volume: float = 1000.0) -> pd.DataFrame:
    """Build a minimal OHLCV frame from a close series."""
    closes_arr = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-02", periods=len(closes_arr)).date,
            "open": closes_arr,
            "high": closes_arr + 1.0,
            "low": closes_arr - 1.0,
            "close": closes_arr,
            "volume": volume,
        }
    )


class TestSma:
    def test_sma5_hand_computed(self) -> None:
        df = compute_indicators(make_ohlcv(list(range(1, 31))))
        # SMA5 of last bar = mean(26..30) = 28
        assert df["sma5"].iloc[-1] == pytest.approx(28.0)

    def test_sma20_hand_computed(self) -> None:
        df = compute_indicators(make_ohlcv([100.0] * 19 + [120.0] * 21))
        # Last 20 closes are all 120.
        assert df["sma20"].iloc[-1] == pytest.approx(120.0)

    def test_sma_nan_when_short_history(self) -> None:
        df = compute_indicators(make_ohlcv(list(range(1, 31))))
        assert df["sma200"].isna().all()  # 30 bars < 200 -> all NaN, never filled


class TestRsi:
    def test_rsi2_monotonic_up_is_100(self) -> None:
        df = compute_indicators(make_ohlcv([float(x) for x in range(100, 160)]))
        assert df["rsi2"].iloc[-1] == pytest.approx(100.0)

    def test_rsi2_monotonic_down_is_0(self) -> None:
        df = compute_indicators(make_ohlcv([float(x) for x in range(160, 100, -1)]))
        assert df["rsi2"].iloc[-1] == pytest.approx(0.0)


class TestZscore:
    def test_zscore_hand_computed(self) -> None:
        closes = [100.0] * 19 + [110.0]
        df = compute_indicators(make_ohlcv(closes))
        mean = (19 * 100.0 + 110.0) / 20  # 100.5
        std = math.sqrt((19 * 0.5**2 + 9.5**2) / 20)  # population std, ddof=0
        expected = (110.0 - mean) / std
        assert df["zscore20"].iloc[-1] == pytest.approx(expected, rel=1e-9)

    def test_zscore_nan_on_constant_series(self) -> None:
        df = compute_indicators(make_ohlcv([100.0] * 25))
        # std=0 -> division guarded to NaN, never inf
        assert pd.isna(df["zscore20"].iloc[-1])


class TestSqueeze:
    def test_flat_series_is_squeezed(self) -> None:
        # BB std=0 (constant close) but KC has width from ATR(high-low=2).
        df = compute_indicators(make_ohlcv([100.0] * 40))
        assert bool(df["squeeze_on"].iloc[-1])

    def test_volatile_series_not_squeezed(self) -> None:
        rng = np.random.default_rng(7)
        closes = list(100 + np.cumsum(rng.normal(0, 8.0, 60)))
        df = make_ohlcv(closes)
        df["high"] = df["close"] + 0.1  # tiny true range -> narrow KC, wide BB
        df["low"] = df["close"] - 0.1
        out = compute_indicators(df)
        assert not bool(out["squeeze_on"].iloc[-1])


class TestRsMomentum:
    def test_composite_ordering_and_exclusion(self) -> None:
        n = 200
        up = pd.Series(np.linspace(100, 200, n))      # strong gainer
        flat = pd.Series(np.full(n, 100.0))            # flat
        down = pd.Series(np.linspace(200, 100, n))     # loser
        short = pd.Series(np.linspace(100, 110, 50))   # insufficient history
        pct = rs_momentum_percentile({"UP": up, "FLAT": flat, "DOWN": down, "SHORT": short})
        assert "SHORT" not in pct  # excluded from denominator, not silently ranked
        assert pct["UP"] > pct["FLAT"] > pct["DOWN"]

    def test_composite_excludes_recent_month(self) -> None:
        # Flat for 180 bars then +50% in the last 21 bars: the jump is entirely
        # inside the skip window, so composite momentum must remain ~0.
        closes = pd.Series([100.0] * 180 + list(np.linspace(100, 150, 21)))
        assert rs_composite(closes) == pytest.approx(0.0, abs=1e-9)


class TestBreadth:
    def test_breadth_50_50(self) -> None:
        above = compute_indicators(make_ohlcv([100.0] * 70 + [120.0] * 10))
        below = compute_indicators(make_ohlcv([100.0] * 70 + [80.0] * 10))
        assert breadth_pct({"A": above, "B": below}) == pytest.approx(50.0)

    def test_short_history_excluded_from_denominator(self) -> None:
        above = compute_indicators(make_ohlcv([100.0] * 70 + [120.0] * 10))
        short = compute_indicators(make_ohlcv([100.0] * 30))  # SMA60 = NaN
        assert breadth_pct({"A": above, "S": short}) == pytest.approx(100.0)
