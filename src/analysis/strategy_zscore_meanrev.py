"""② Z-Score Mean Reversion (Z-Score 평균회귀): statistical extreme oversold.

Strength scales CONTINUOUSLY with |zscore| depth and volume multiple — the
quantified extremity is what separates this from binary band-touch logic.
"""

import pandas as pd

from config import settings
from src.analysis.base_strategy import BaseStrategy, Signal
from src.analysis.registry import register


@register
class ZScoreMeanRevStrategy(BaseStrategy):
    """Buy(ALL): zscore<-2.5; bullish recovery bar; vol>1.5xVolMA20; price floor."""

    strategy_id = "zscore_meanrev"
    name_kr = "Z-Score 평균회귀"

    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        if len(df) < 2:
            return None
        row, prev = df.iloc[-1], df.iloc[-2]
        p = self.params
        if pd.isna(row["zscore20"]) or pd.isna(row["vol_ma20"]):
            return None
        price_floor = settings.KR_MIN_PRICE if market == "kr" else settings.US_MIN_PRICE
        bullish_recovery = row["close"] > row["open"] or row["close"] > prev["close"]
        conditions = (
            row["zscore20"] < p["z_entry"]
            and bullish_recovery
            and row["volume"] > p["vol_mult"] * row["vol_ma20"]
            and row["close"] >= price_floor
        )
        if not conditions:
            return None
        z = float(row["zscore20"])
        vol_ratio = float(row["volume"] / row["vol_ma20"])
        # Continuous scaling: deeper extremity and heavier volume = stronger.
        z_depth = min(1.0, (abs(z) - abs(p["z_entry"])) / 1.5)  # -2.5 -> 0, -4.0 -> 1
        vol_score = min(1.0, (vol_ratio - p["vol_mult"]) / 2.0)
        strength = round(55 + 30 * z_depth + 15 * vol_score, 1)
        price = float(row["close"])
        return Signal(
            ticker=ticker,
            name=name,
            market=market,
            strategy_id=self.strategy_id,
            direction="BUY",
            strength=strength,
            price=price,
            signal_date=row["date"] if "date" in row else df.index[-1],
            indicators=self._snapshot(row, ["zscore20", "rsi14", "sma20", "vol_ma20"]),
            suggested_stop_loss=round(price * (1 - p["stop_loss_pct"] / 100), 4),
            suggested_take_profit=None,  # exit at z>=0 (mean reversion) or time stop
            exit_mode=self.exit_mode,
            reason=(
                f"20일 평균 대비 {z:+.1f} 표준편차 — 통계적 극단 과매도에서 "
                f"반등 양봉 출현, 거래량 평소의 {vol_ratio:.1f}배"
            ),
        )
