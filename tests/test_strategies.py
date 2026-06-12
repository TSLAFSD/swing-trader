"""Strategy entry-condition tests on hand-crafted synthetic frames.

Each frame sets exactly the indicator columns the strategy reads, so every
condition is verifiable by hand. One positive + one broken-condition case per
strategy, plus confluence merge tests.
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.base_strategy import load_strategy_config
from src.analysis.strategy_breakout import BreakoutStrategy
from src.analysis.strategy_connors_rsi2 import ConnorsRsi2Strategy
from src.analysis.strategy_pullback import PullbackStrategy
from src.analysis.strategy_squeeze import SqueezeStrategy
from src.analysis.strategy_wyckoff import WyckoffSpringStrategy
from src.analysis.strategy_zscore_meanrev import ZScoreMeanRevStrategy

CFG = load_strategy_config()  # real YAML: single source of truth


def base_frame(n: int = 260, close: float = 50.0, volume: float = 1_000_000.0) -> pd.DataFrame:
    """Neutral frame with all indicator columns present and conditions FALSE."""
    df = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-02", periods=n).date,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": volume,
            "sma5": close,
            "sma20": close,
            "sma60": close,
            "sma200": close,
            "rsi2": 50.0,
            "rsi14": 50.0,
            "adx14": 15.0,
            "atr14": 1.0,
            "bb_mid": close,
            "bb_lower": close - 2,
            "bb_upper": close + 2,
            "kc_lower": close - 3,
            "kc_upper": close + 3,
            "vol_ma20": volume,
            "zscore20": 0.0,
            "squeeze_on": False,
            "linreg_slope20": 0.0,
            "prior_high60": close + 10,
            "pct_change_1d": 0.0,
        }
    )
    return df


class TestPullback:
    def fire_frame(self) -> pd.DataFrame:
        df = base_frame()
        last = df.index[-1]
        df.loc[last, ["close", "sma20", "sma60", "rsi14", "adx14", "bb_mid"]] = [
            52.0, 53.0, 50.0, 35.0, 25.0, 52.5,
        ]  # close>sma60, sma20>sma60, rsi<40, adx>20, close<=bb_mid
        return df

    def test_fires(self) -> None:
        sig = PullbackStrategy(CFG).evaluate(self.fire_frame(), "TEST", "테스트", "us")
        assert sig is not None and sig.direction == "BUY"
        assert sig.suggested_stop_loss == pytest.approx(52.0 * 0.95)
        assert sig.suggested_take_profit == pytest.approx(52.0 * 1.15)
        assert 0 <= sig.strength <= 100

    def test_blocked_by_high_rsi(self) -> None:
        df = self.fire_frame()
        df.loc[df.index[-1], "rsi14"] = 45.0  # breaks RSI<40
        assert PullbackStrategy(CFG).evaluate(df, "TEST", "테스트", "us") is None


class TestZScoreMeanRev:
    def fire_frame(self) -> pd.DataFrame:
        df = base_frame()
        last = df.index[-1]
        df.loc[df.index[-2], "close"] = 49.0
        df.loc[last, ["close", "open", "zscore20", "volume"]] = [50.0, 48.0, -3.0, 2_000_000.0]
        return df

    def test_fires_and_strength_scales_with_depth(self) -> None:
        strat = ZScoreMeanRevStrategy(CFG)
        shallow = strat.evaluate(self.fire_frame(), "TEST", "테스트", "us")
        deep_df = self.fire_frame()
        deep_df.loc[deep_df.index[-1], "zscore20"] = -4.0
        deep = strat.evaluate(deep_df, "TEST", "테스트", "us")
        assert shallow is not None and deep is not None
        assert deep.strength > shallow.strength  # continuous extremity scaling

    def test_blocked_without_recovery_bar(self) -> None:
        df = self.fire_frame()
        df.loc[df.index[-2], "close"] = 51.0
        df.loc[df.index[-1], ["close", "open"]] = [50.0, 50.5]  # bearish, below prev
        assert ZScoreMeanRevStrategy(CFG).evaluate(df, "TEST", "테스트", "us") is None


class TestConnorsRsi2:
    def test_fires(self) -> None:
        df = base_frame()
        df.loc[df.index[-1], ["close", "rsi2", "sma200"]] = [50.0, 5.0, 45.0]
        sig = ConnorsRsi2Strategy(CFG).evaluate(df, "TEST", "테스트", "us")
        assert sig is not None
        assert sig.suggested_stop_loss == pytest.approx(50.0 * 0.94)

    def test_blocked_below_sma200(self) -> None:
        df = base_frame()
        df.loc[df.index[-1], ["close", "rsi2", "sma200"]] = [50.0, 5.0, 55.0]
        assert ConnorsRsi2Strategy(CFG).evaluate(df, "TEST", "테스트", "us") is None


class TestBreakout:
    def test_fires(self) -> None:
        df = base_frame()
        df.loc[df.index[-1], ["close", "prior_high60", "volume", "adx14", "sma60"]] = [
            61.0, 60.0, 2_000_000.0, 25.0, 50.0,
        ]
        sig = BreakoutStrategy(CFG).evaluate(df, "TEST", "테스트", "us")
        assert sig is not None
        assert sig.exit_mode == "atr_trailing"
        assert sig.suggested_stop_loss == pytest.approx(61.0 - 3.0 * 1.0)  # close - k*ATR

    def test_blocked_by_low_volume(self) -> None:
        df = base_frame()
        df.loc[df.index[-1], ["close", "prior_high60", "volume", "adx14"]] = [
            61.0, 60.0, 1_200_000.0, 25.0,  # 1.2x < required 1.5x
        ]
        assert BreakoutStrategy(CFG).evaluate(df, "TEST", "테스트", "us") is None


class TestSqueeze:
    def fire_frame(self) -> pd.DataFrame:
        df = base_frame()
        df.loc[df.index[-9:-1], "squeeze_on"] = True  # 8-day squeeze ending yesterday
        df.loc[df.index[-2], "high"] = 50.5
        df.loc[df.index[-1], ["close", "squeeze_on", "volume", "linreg_slope20"]] = [
            51.5, False, 1_500_000.0, 0.2,
        ]
        return df

    def test_fires(self) -> None:
        sig = SqueezeStrategy(CFG).evaluate(self.fire_frame(), "TEST", "테스트", "us")
        assert sig is not None
        assert sig.suggested_stop_loss <= 50.0 - 0.5  # below squeeze-range low

    def test_blocked_without_release(self) -> None:
        df = self.fire_frame()
        df.loc[df.index[-1], "squeeze_on"] = True  # still squeezed
        assert SqueezeStrategy(CFG).evaluate(df, "TEST", "테스트", "us") is None


class TestWyckoffSpring:
    def fire_frame(self) -> pd.DataFrame:
        # 60d range 48..52 (width 8.3% < 15%), spring: yesterday low 47 close 49.
        df = base_frame(n=260, close=50.0)
        df["high"] = 52.0
        df["low"] = 48.0
        idx = df.index
        df.loc[idx[-2], ["low", "close"]] = [47.0, 49.0]
        df.loc[idx[-1], ["open", "close", "low", "high", "volume"]] = [
            49.0, 50.5, 48.5, 50.8, 1_500_000.0,
        ]
        return df

    def test_fires(self) -> None:
        sig = WyckoffSpringStrategy(CFG).evaluate(self.fire_frame(), "TEST", "테스트", "us")
        assert sig is not None
        assert sig.suggested_stop_loss < 47.0 * 1.001  # just below spring low

    def test_blocked_by_wide_range(self) -> None:
        df = self.fire_frame()
        df.loc[df.index[:-2], "high"] = 60.0  # range width ~25% > 15% cap
        assert WyckoffSpringStrategy(CFG).evaluate(df, "TEST", "테스트", "us") is None


# (Confluence merge-layer tests removed in U1/A-4 along with the module.)
