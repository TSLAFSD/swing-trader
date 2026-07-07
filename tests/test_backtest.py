"""Backtester/validation unit tests: stats, Monte Carlo, regime slicing."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.backtester import aggregate_stats
from src.backtest.validation import monte_carlo, regime_series


def trades_frame(returns: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry_time": pd.date_range("2025-01-01", periods=len(returns)),
            "exit_time": pd.date_range("2025-01-05", periods=len(returns)),
            "return_pct": returns,
            "holding_days": 4,
        }
    )


class TestAggregateStats:
    def test_hand_computed(self) -> None:
        stats = aggregate_stats(trades_frame([0.10, -0.05, 0.02, -0.01]))
        assert stats["n"] == 4
        assert stats["win_rate"] == pytest.approx(0.5)
        assert stats["profit_factor"] == pytest.approx(0.12 / 0.06)  # 2.0

    def test_empty(self) -> None:
        stats = aggregate_stats(trades_frame([]))
        assert stats["n"] == 0 and np.isnan(stats["profit_factor"])

    def test_no_losses_is_inf(self) -> None:
        assert np.isinf(aggregate_stats(trades_frame([0.05, 0.02]))["profit_factor"])


class TestMonteCarlo:
    def test_deterministic_for_constant_returns(self) -> None:
        # All trades +1%: every bootstrap path identical, MDD 0.
        p5_final, p95_mdd = monte_carlo(pd.Series([0.01] * 30), runs=200)
        assert p5_final == pytest.approx(1.01**30, rel=1e-9)
        assert p95_mdd == pytest.approx(0.0, abs=1e-12)

    def test_volatile_returns_have_drawdown(self) -> None:
        rng = np.random.default_rng(1)
        returns = pd.Series(rng.normal(0.0, 0.05, 100))
        _, p95_mdd = monte_carlo(returns, runs=300)
        assert p95_mdd > 10.0  # noisy sequence must show meaningful tail MDD

    def test_empty_returns_nan(self) -> None:
        p5, mdd = monte_carlo(pd.Series([], dtype=float), runs=100)
        assert np.isnan(p5) and np.isnan(mdd)


class TestRegimeSeries:
    def test_classifies_trend_phases(self) -> None:
        idx = pd.date_range("2023-01-01", periods=300)
        up = np.linspace(100, 200, 150)
        down = np.linspace(200, 120, 150)
        series = pd.Series(np.concatenate([up, down]), index=idx)
        regimes = regime_series(series)
        assert regimes.iloc[120] == "bull"   # late in the climb
        assert regimes.iloc[290] == "bear"   # late in the slide
        assert set(regimes.unique()) <= {"bull", "bear", "sideways"}


class TestStrategyFilter:
    def test_filter_keeps_only_requested(self) -> None:
        from src.analysis.registry import get_strategies
        from src.backtest.run_validation import filter_strategies

        strategies = get_strategies(enabled_only=False)
        kept = filter_strategies(strategies, "zscore_meanrev")
        assert [s.strategy_id for s in kept] == ["zscore_meanrev"]

    def test_filter_none_keeps_all(self) -> None:
        from src.analysis.registry import get_strategies
        from src.backtest.run_validation import filter_strategies

        strategies = get_strategies(enabled_only=False)
        assert filter_strategies(strategies, None) == list(strategies)

    def test_filter_unknown_raises(self) -> None:
        import pytest

        from src.analysis.registry import get_strategies
        from src.backtest.run_validation import filter_strategies

        with pytest.raises(ValueError, match="unknown strategy"):
            filter_strategies(get_strategies(enabled_only=False), "nope")
