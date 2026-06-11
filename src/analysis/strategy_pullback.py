"""① Pullback (눌림목): dip-buy within an established mid-term uptrend."""

import pandas as pd

from src.analysis.base_strategy import BaseStrategy, Signal
from src.analysis.registry import register


@register
class PullbackStrategy(BaseStrategy):
    """Buy(ALL): close>SMA60; SMA20>SMA60; RSI14<40; ADX>20; vol>0.7xVolMA20; close<=BB mid."""

    strategy_id = "pullback"
    name_kr = "눌림목"

    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        row = df.iloc[-1]
        p = self.params
        required = ["sma20", "sma60", "rsi14", "adx14", "vol_ma20", "bb_mid"]
        if row[required].isna().any():
            return None
        conditions = (
            row["close"] > row[f"sma{p['trend_sma']}"]
            and row[f"sma{p['pull_sma']}"] > row[f"sma{p['trend_sma']}"]
            and row["rsi14"] < p["rsi_max"]
            and row["adx14"] > p["adx_min"]
            and row["volume"] > p["vol_ratio_min"] * row["vol_ma20"]
            and row["close"] <= row["bb_mid"]
        )
        if not conditions:
            return None
        # Deeper RSI dip within an intact trend = stronger setup.
        rsi_depth = (p["rsi_max"] - row["rsi14"]) / p["rsi_max"]  # 0..1
        trend_quality = min(1.0, (row["adx14"] - p["adx_min"]) / 20.0)
        strength = round(50 + 35 * rsi_depth + 15 * trend_quality, 1)
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
            indicators=self._snapshot(row, ["rsi14", "adx14", "sma20", "sma60", "bb_mid", "zscore20"]),
            suggested_stop_loss=round(price * (1 - p["stop_loss_pct"] / 100), 4),
            suggested_take_profit=round(price * (1 + p["take_profit_pct"] / 100), 4),
            exit_mode=self.exit_mode,
            reason=(
                f"상승 추세(60일선 위) 중 눌림목 — RSI {row['rsi14']:.0f}로 단기 조정, "
                f"ADX {row['adx14']:.0f}로 추세 유지"
            ),
        )
