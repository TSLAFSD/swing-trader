"""③ Connors RSI(2) (단기 과매도 반등): Larry Connors short-term mean reversion.

The mandatory SMA200 long-term uptrend filter is what separates this from
naive dip-buying.
"""

import pandas as pd

from config import settings
from src.analysis.base_strategy import BaseStrategy, Signal
from src.analysis.registry import register


@register
class ConnorsRsi2Strategy(BaseStrategy):
    """Buy(ALL): RSI(2)<10; close>SMA200; price floor."""

    strategy_id = "connors_rsi2"
    name_kr = "단기 과매도 반등"

    def should_exit(self, df: pd.DataFrame) -> str | None:
        row = df.iloc[-1]
        p = self.params
        if pd.notna(row["rsi2"]) and row["rsi2"] > p["rsi2_exit"]:
            return f"RSI(2) {row['rsi2']:.0f} 반등 완료 (> {p['rsi2_exit']})"
        if pd.notna(row[f"sma{p['exit_sma']}"]) and row["close"] > row[f"sma{p['exit_sma']}"]:
            return f"{p['exit_sma']}일선 회복"
        return None

    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        row = df.iloc[-1]
        p = self.params
        if pd.isna(row["rsi2"]) or pd.isna(row["sma200"]):
            return None
        price_floor = settings.KR_MIN_PRICE if market == "kr" else settings.US_MIN_PRICE
        conditions = (
            row["rsi2"] < p["rsi2_entry"]
            and row["close"] > row["sma200"]
            and row["close"] >= price_floor
        )
        if not conditions:
            return None
        # Deeper RSI(2) and more headroom above SMA200 = stronger.
        rsi_depth = (p["rsi2_entry"] - row["rsi2"]) / p["rsi2_entry"]  # 0..1
        trend_headroom = min(1.0, (row["close"] / row["sma200"] - 1.0) / 0.15)
        strength = round(50 + 35 * rsi_depth + 15 * trend_headroom, 1)
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
            indicators=self._snapshot(row, ["rsi2", "rsi14", "sma200", "sma5", "zscore20"]),
            suggested_stop_loss=round(price * (1 - p["stop_loss_pct"] / 100), 4),
            suggested_take_profit=None,  # exit at RSI(2)>65 or close>SMA5 or time stop
            exit_mode=self.exit_mode,
            reason=(
                f"RSI(2) {row['rsi2']:.0f} — 초단기 과매도, "
                f"주가는 200일선 위 장기 상승 추세 유지 중"
            ),
        )
