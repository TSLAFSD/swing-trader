"""Wyckoff VPA engine tests on hand-crafted synthetic OHLCV.

Covers: full spring pattern, volume-deficient climax, exhaustion unmet,
climax-low re-break invalidation, NO-REPAINT guarantee, UTAD mirror symmetry,
Weis wave hand-computed values.
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.wyckoff_vpa import (
    detect_buying_climax,
    detect_demand_exhaustion,
    detect_liquidity_high,
    detect_liquidity_low,
    detect_selling_climax,
    detect_supply_exhaustion,
    weis_waves,
)

VPA = dict(lookback=60, pivot_strength=3, equal_low_pct=0.5)
CLIMAX = dict(vol_ma_days=20, vol_mult=2.0, wick_body_ratio=2.0)


def make_df(closes, lows=None, highs=None, opens=None, volumes=None) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    lows = np.asarray(lows, dtype=float) if lows is not None else closes - 0.4
    highs = np.asarray(highs, dtype=float) if highs is not None else closes + 0.4
    opens = np.asarray(opens, dtype=float) if opens is not None else closes.copy()
    volumes = np.asarray(volumes, dtype=float) if volumes is not None else np.full(n, 1000.0)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-02", periods=n).date,
            "open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes,
        }
    )


def spring_frame(climax_vol: float = 3500.0, retest_vol: float = 400.0,
                 retest_close: float = 97.9) -> pd.DataFrame:
    """39-bar spring: equal lows ~99.0 -> SC sweep to 96.5 -> low-vol retest."""
    closes = [100.0] * 25 + [99.0, 98.2, 97.4, 97.0, 100.2,        # down leg + climax(29)
              100.6, 100.9, 101.0,                                  # up wave
              99.0, retest_close, 97.95,                            # retest wave (low vol)
              99.5, 100.3, 100.9]                                   # final up leg
    lows = [c - 0.4 for c in closes]
    lows[10], lows[20] = 99.00, 99.04   # equal-low pivots (cluster within 0.5%)
    lows[29] = 96.5                      # climax sweep below level
    opens = list(closes)
    opens[29] = 97.2                     # climax bar: open 97.2 -> close 100.2
    volumes = [1000.0] * 39
    volumes[29] = climax_vol
    for i in (33, 34, 35):
        volumes[i] = retest_vol
    return make_df(closes, lows=lows, opens=opens, volumes=volumes)


class TestSpringPattern:
    def test_full_three_stages(self) -> None:
        df = spring_frame()
        level = detect_liquidity_low(df, **VPA)
        assert level is not None
        assert level.level == pytest.approx(99.00)
        assert level.touch_count == 2
        climax = detect_selling_climax(df, level.level, **CLIMAX)
        assert climax is not None
        assert climax.sweep_idx == 29
        assert climax.climax_low == pytest.approx(96.5)
        assert climax.recovery_type == "close_recovery"
        assert climax.volume_ratio > 2.0
        waves = weis_waves(df, zigzag_pct=3.0)
        exhaustion = detect_supply_exhaustion(waves, climax, retest_window=10, exhaust_ratio=0.5)
        assert exhaustion is not None
        assert exhaustion.test_volume_ratio <= 0.5

    def test_volume_deficient_climax_rejected(self) -> None:
        df = spring_frame(climax_vol=1500.0)  # 1.5x < required 2.0x
        level = detect_liquidity_low(df, **VPA)
        assert level is not None
        assert detect_selling_climax(df, level.level, **CLIMAX) is None

    def test_exhaustion_unmet_when_retest_volume_heavy(self) -> None:
        # Climax wave spans 28 bars (cum 28,000); retest must exceed half of
        # that to fail the exhaustion test -> 2 bars x 8,000 = 0.57 ratio.
        df = spring_frame(retest_vol=8000.0)
        level = detect_liquidity_low(df, **VPA)
        climax = detect_selling_climax(df, level.level, **CLIMAX)
        waves = weis_waves(df, zigzag_pct=3.0)
        assert detect_supply_exhaustion(waves, climax, 10, 0.5) is None

    def test_invalidated_when_retest_breaks_climax_low(self) -> None:
        df = spring_frame(retest_close=96.0)  # retest closes below climax low 96.5
        level = detect_liquidity_low(df, **VPA)
        climax = detect_selling_climax(df, level.level, **CLIMAX)
        waves = weis_waves(df, zigzag_pct=3.0)
        assert detect_supply_exhaustion(waves, climax, 10, 0.5) is None


class TestNoRepaint:
    def test_pivot_unusable_before_right_side_confirms(self) -> None:
        df = spring_frame()
        # Pivot at bar 10 needs bars 11-13. Truncated at bar 12 -> NO level at all.
        assert detect_liquidity_low(df.iloc[:13].reset_index(drop=True), **VPA) is None
        # At bar 13 the first pivot confirms -> level exists with ONE touch.
        early = detect_liquidity_low(df.iloc[:14].reset_index(drop=True), **VPA)
        assert early is not None and early.touch_count == 1
        # Pivot at bar 20 confirms only at bar 23: truncated at 22 -> still 1 touch.
        mid = detect_liquidity_low(df.iloc[:23].reset_index(drop=True), **VPA)
        assert mid is not None and mid.touch_count == 1
        # Full history -> 2 touches; confirmed_date == bar 23's date, never earlier.
        full = detect_liquidity_low(df, **VPA)
        assert full.touch_count == 2
        assert full.confirmed_date == df["date"].iloc[23]


class TestUtadMirror:
    def mirror(self, df: pd.DataFrame) -> pd.DataFrame:
        """Price-mirror around 200: lows<->highs, opens/closes reflected."""
        out = df.copy()
        out["close"] = 200.0 - df["close"]
        out["open"] = 200.0 - df["open"]
        out["high"] = 200.0 - df["low"]
        out["low"] = 200.0 - df["high"]
        return out

    def test_sell_side_symmetry(self) -> None:
        df = self.mirror(spring_frame())
        level = detect_liquidity_high(df, lookback=60, pivot_strength=3, equal_high_pct=0.5)
        assert level is not None
        assert level.level == pytest.approx(200.0 - 99.00)  # mirrored equal highs
        assert level.touch_count == 2
        climax = detect_buying_climax(df, level.level, **CLIMAX)
        assert climax is not None
        assert climax.extreme == pytest.approx(200.0 - 96.5)  # UTAD high
        waves = weis_waves(df, zigzag_pct=3.0)
        exhaustion = detect_demand_exhaustion(waves, climax, 10, 0.5)
        assert exhaustion is not None
        assert exhaustion.test_volume_ratio <= 0.5


class TestWeisWaves:
    def test_hand_computed_waves(self) -> None:
        # 100 ->(up)-> 104 ->(down)-> 99 ->(up)-> 103.5; zigzag 3%
        closes = [100, 102, 104, 102.5, 99, 101, 103.5]
        volumes = [10, 20, 30, 40, 50, 60, 70]
        waves = weis_waves(make_df(closes, volumes=volumes), zigzag_pct=3.0)
        assert list(waves["direction"]) == [1, -1, 1]
        # Wave 1: bars 1-2 (vol 20+30); wave 2: bars 3-4 (40+50); wave 3: bars 5-6.
        assert list(waves["cum_volume"]) == [50.0, 90.0, 130.0]
        assert waves.iloc[1]["price_range"] == pytest.approx(5.0)  # 104 -> 99

    def test_sub_threshold_move_does_not_flip(self) -> None:
        closes = [100, 104, 101.2, 104.5]  # -2.7% pullback: no down wave
        waves = weis_waves(make_df(closes), zigzag_pct=3.0)
        assert (waves["direction"] == -1).sum() == 0

    def test_empty_and_tiny_inputs(self) -> None:
        assert weis_waves(make_df([100.0])).empty
        assert weis_waves(make_df([100.0, 100.5])).empty  # no threshold move
