"""⑥ Wyckoff Spring (와이코프 스프링): mechanizable subset only, NO phase classification.

Range-bound base; a recent bar's low pierced the range low but CLOSED back
above it (the spring), with recovery volume and a bullish close.
"""

import pandas as pd

from src.analysis.base_strategy import BaseStrategy, Signal
from src.analysis.registry import register


@register
class WyckoffSpringStrategy(BaseStrategy):
    """Buy(ALL): tight 60d range; spring within last 3 days; recovery volume; bullish close."""

    strategy_id = "wyckoff_spring"
    name_kr = "와이코프 스프링"

    def _range_bounds(self, df: pd.DataFrame) -> tuple[float, float] | None:
        """(range_low, range_high) measured BEFORE the spring window; None if short."""
        p = self.params
        range_days, lookback = int(p["range_days"]), int(p["spring_lookback"])
        if len(df) < range_days + lookback + 1:
            return None
        base = df.iloc[-(range_days + lookback) : -lookback]
        return float(base["low"].min()), float(base["high"].max())

    def conditions(self, df: pd.DataFrame) -> list[tuple[str, bool]]:
        p = self.params
        row = df.iloc[-1]
        bounds = self._range_bounds(df)
        if bounds is None or bounds[0] <= 0:
            return [(f"{p['range_days']}일 박스권 형성", False)]
        range_low, range_high = bounds
        width_pct = (range_high - range_low) / range_low * 100
        window = df.iloc[-int(p["spring_lookback"]) :]
        sprung = bool(((window["low"] < range_low) & (window["close"] > range_low)).any())
        return [
            (f"박스권 폭 < {p['range_max_width_pct']}% (현재 {width_pct:.1f}%)",
             width_pct < p["range_max_width_pct"]),
            (f"최근 {p['spring_lookback']}일 내 스프링 (저가 이탈 후 회복)", sprung),
            ("종가가 박스 하단 위", pd.notna(row["close"]) and row["close"] > range_low),
            (f"회복 거래량 > 평소의 {p['vol_mult']}배",
             pd.notna(row["vol_ma20"]) and row["volume"] > p["vol_mult"] * row["vol_ma20"]),
            ("양봉 마감", pd.notna(row["close"]) and row["close"] > row["open"]),
        ]

    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        bounds = self._range_bounds(df)
        if bounds is None or bounds[0] <= 0:
            return None
        if not all(ok for _, ok in self.conditions(df)):
            return None
        row = df.iloc[-1]
        p = self.params
        if pd.isna(row["atr14"]):
            return None
        range_low, range_high = bounds
        range_width_pct = (range_high - range_low) / range_low * 100
        window = df.iloc[-int(p["spring_lookback"]) :]
        spring_low = float(window["low"].min())
        vol_ratio = float(row["volume"] / row["vol_ma20"])
        # Tighter range and stronger recovery volume = better spring.
        tightness = 1.0 - range_width_pct / p["range_max_width_pct"]
        strength = round(55 + 25 * tightness + 20 * min(1.0, (vol_ratio - p["vol_mult"]) / 2.0), 1)
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
            indicators=self._snapshot(row, ["atr14", "vol_ma20", "zscore20"]),
            suggested_stop_loss=round(spring_low * 0.995, 4),  # just below spring low
            suggested_take_profit=round(range_high, 4),  # range high -> then ATR trailing
            exit_mode=self.exit_mode,
            reason=(
                f"{int(p['range_days'])}일 박스권(폭 {range_width_pct:.1f}%) 하단 이탈 후 "
                f"즉시 회복(스프링) — 회복 거래량 평소의 {vol_ratio:.1f}배"
            ),
        )
