"""④ Breakout (돌파): new 60-day high with volume and trend confirmation."""

import pandas as pd

from src.analysis.base_strategy import BaseStrategy, Signal
from src.analysis.registry import register


@register
class BreakoutStrategy(BaseStrategy):
    """Buy(ALL): close > prior 60d high (excl. today); vol>1.5x; ADX>20; close>SMA60."""

    strategy_id = "breakout"
    name_kr = "돌파"

    def should_exit(self, df: pd.DataFrame) -> str | None:
        row = df.iloc[-1]
        if pd.notna(row["sma20"]) and row["close"] < row["sma20"]:
            return "20일선 이탈"
        return None

    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        row = df.iloc[-1]
        p = self.params
        required = ["prior_high60", "vol_ma20", "adx14", "sma60", "atr14"]
        if row[required].isna().any():
            return None
        conditions = (
            row["close"] > row["prior_high60"]
            and row["volume"] > p["vol_mult"] * row["vol_ma20"]
            and row["adx14"] > p["adx_min"]
            and row["close"] > row[f"sma{p['trend_sma']}"]
        )
        if not conditions:
            return None
        vol_ratio = float(row["volume"] / row["vol_ma20"])
        breakout_margin = float(row["close"] / row["prior_high60"] - 1.0)
        strength = round(
            55
            + 25 * min(1.0, (vol_ratio - p["vol_mult"]) / 2.0)
            + 20 * min(1.0, breakout_margin / 0.05),
            1,
        )
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
            indicators=self._snapshot(row, ["prior_high60", "adx14", "atr14", "vol_ma20"]),
            suggested_stop_loss=round(price - p["atr_k"] * float(row["atr14"]), 4),
            suggested_take_profit=None,  # ATR trailing exit
            exit_mode=self.exit_mode,
            reason=(
                f"60일 신고가 돌파 (+{breakout_margin * 100:.1f}%), "
                f"거래량 평소의 {vol_ratio:.1f}배, ADX {row['adx14']:.0f}"
            ),
        )
