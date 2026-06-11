"""Phase 1 execution gate: synthetic 100-bar OHLCV through backtesting.py,
plus a pandas-ta runtime sanity check (imports passing != execution passing).

Run: .venv/bin/python tests/mini_backtest_phase1.py
"""

import logging

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RNG_SEED = 42
N_BARS = 100


def make_synthetic_ohlcv(n_bars: int) -> pd.DataFrame:
    """Build a deterministic synthetic OHLCV frame with a mild uptrend.

    Args:
        n_bars: Number of daily bars to generate.

    Returns:
        DataFrame indexed by business day with Open/High/Low/Close/Volume.
    """
    rng = np.random.default_rng(RNG_SEED)
    drift = np.linspace(0, 15, n_bars)
    noise = rng.normal(0, 1.5, n_bars).cumsum()
    close = 100 + drift + noise
    open_ = close + rng.normal(0, 0.5, n_bars)
    high = np.maximum(open_, close) + rng.uniform(0.1, 1.0, n_bars)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.0, n_bars)
    volume = rng.integers(50_000, 200_000, n_bars).astype(float)
    index = pd.bdate_range("2025-01-02", periods=n_bars)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=index,
    )


class SmaCross(Strategy):
    """Trivial SMA(5/20) crossover, long-only, for stack verification."""

    n_fast = 5
    n_slow = 20

    def init(self) -> None:
        close = pd.Series(self.data.Close)
        self.sma_fast = self.I(lambda: ta.sma(close, length=self.n_fast))
        self.sma_slow = self.I(lambda: ta.sma(close, length=self.n_slow))

    def next(self) -> None:
        if crossover(self.sma_fast, self.sma_slow):
            self.buy()
        elif crossover(self.sma_slow, self.sma_fast):
            self.position.close()


def check_pandas_ta(df: pd.DataFrame) -> None:
    """Run the pandas-ta functions the project depends on; raise on failure."""
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    results = {
        "sma20": ta.sma(close, length=20),
        "rsi14": ta.rsi(close, length=14),
        "rsi2": ta.rsi(close, length=2),
        "macd": ta.macd(close),
        "bbands": ta.bbands(close, length=20, std=2),
        "kc": ta.kc(high, low, close, length=20, scalar=1.5),
        "adx14": ta.adx(high, low, close, length=14),
        "stoch": ta.stoch(high, low, close),
        "atr14": ta.atr(high, low, close, length=14),
        "obv": ta.obv(close, vol),
    }
    for name, out in results.items():
        if out is None or len(out) != len(df) or np.all(pd.isna(out.iloc[-1])):
            raise RuntimeError(f"pandas-ta {name} returned invalid output")
        last = out.iloc[-1]
        shown = f"{last:.4f}" if np.isscalar(last) else "/".join(f"{v:.2f}" for v in last)
        logger.info("pandas-ta %-7s last=%s", name, shown)
    logger.info("--- PANDAS-TA RUNTIME OK ---")


def main() -> None:
    """Run the pandas-ta sanity check and the mini backtest."""
    df = make_synthetic_ohlcv(N_BARS)
    check_pandas_ta(df)

    bt = Backtest(df, SmaCross, cash=10_000, commission=0.00015, exclusive_orders=True)
    stats = bt.run()
    print(stats)
    print("--- MINI BACKTEST OK ---")


if __name__ == "__main__":
    main()
