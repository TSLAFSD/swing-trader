"""Per-ticker confidence (spec §7 Layer 2): signal tickers only, never full universe.

Backtests one strategy on one ticker's own history. Min-sample rule:
< CONF_MIN_TRADES trades -> confidence capped at CONF_CAP_LOW_SAMPLE and
labeled "표본 부족 — 신뢰 불가". Final scan rank = strength x confidence.
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import settings
from src.analysis.base_strategy import BaseStrategy
from src.backtest.backtester import aggregate_stats, generate_entry_plan, run_backtest

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceReport:
    """Per-(ticker, strategy) historical backtest summary."""

    ticker: str
    strategy_id: str
    n_trades: int
    win_rate: float
    profit_factor: float
    avg_holding_days: float
    max_drawdown_pct: float
    score: float  # 0..1 multiplier for signal strength
    label_kr: str
    avg_win: float = float("nan")  # mean winning-trade return (fraction)
    avg_loss: float = float("nan")  # mean losing-trade return (fraction, negative)

    @property
    def low_sample(self) -> bool:
        """True when the min-sample rule capped this report."""
        return self.n_trades < settings.CONF_MIN_TRADES


def _trade_sequence_mdd(returns: pd.Series) -> float:
    """MDD (%) of the compounded trade-sequence equity curve."""
    if returns.empty:
        return float("nan")
    equity = np.cumprod(1.0 + returns.to_numpy())
    peak = np.maximum.accumulate(equity)
    return float(-((equity - peak) / peak).min() * 100.0)


def ticker_confidence(
    df_ind: pd.DataFrame, strategy: BaseStrategy, ticker: str, market: str
) -> ConfidenceReport:
    """Backtest the strategy on this ticker's history and score confidence.

    Score = 0.5 * win_rate + 0.5 * min(PF, 2) / 2, capped by the min-sample rule.

    Args:
        df_ind: Full-history indicator frame for the ticker.
        strategy: Strategy instance.
        ticker: Ticker code.
        market: "us" | "kr".

    Returns:
        ConfidenceReport (score 0 when the ticker never traded).
    """
    plan = generate_entry_plan(df_ind, strategy, ticker, market)
    trades = run_backtest(df_ind, plan, strategy, market)
    stats = aggregate_stats(trades)
    n = stats["n"]
    if n == 0:
        return ConfidenceReport(
            ticker=ticker, strategy_id=strategy.strategy_id, n_trades=0,
            win_rate=float("nan"), profit_factor=float("nan"),
            avg_holding_days=float("nan"), max_drawdown_pct=float("nan"),
            score=0.0, label_kr="과거 시그널 없음 — 신뢰도 평가 불가",
        )
    wr, pf = stats["win_rate"], stats["profit_factor"]
    pf_part = 1.0 if np.isinf(pf) else min(pf, 2.0) / 2.0
    score = 0.5 * wr + 0.5 * pf_part
    if n < settings.CONF_MIN_TRADES:
        score = min(score, settings.CONF_CAP_LOW_SAMPLE)
        label = f"표본 부족 ({n}건) — 신뢰 불가"
    elif score >= 0.6:
        label = f"과거 {n}건 승률 {wr * 100:.0f}% — 양호"
    else:
        label = f"과거 {n}건 승률 {wr * 100:.0f}% — 주의"
    r = trades["return_pct"]
    wins, losses = r[r > 0], r[r < 0]
    return ConfidenceReport(
        ticker=ticker, strategy_id=strategy.strategy_id, n_trades=n,
        win_rate=wr, profit_factor=pf, avg_holding_days=stats["avg_holding"],
        max_drawdown_pct=_trade_sequence_mdd(r),
        score=round(score, 3), label_kr=label,
        avg_win=float(wins.mean()) if len(wins) else float("nan"),
        avg_loss=float(losses.mean()) if len(losses) else float("nan"),
    )
