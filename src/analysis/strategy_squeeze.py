"""⑤ Squeeze Breakout (변동성 스퀴즈): TTM-style volatility-contraction release.

BB(20,2) fully inside Keltner(20,1.5xATR) for >= N days = squeeze ON;
buy on release with an up-bar + volume + positive momentum proxy.
"""

import pandas as pd

from src.analysis.base_strategy import BaseStrategy, Signal
from src.analysis.registry import register


@register
class SqueezeStrategy(BaseStrategy):
    """Buy: squeeze releases with close>prior high, vol>1.2x, linreg slope>0."""

    strategy_id = "squeeze"
    name_kr = "변동성 스퀴즈"

    def _squeeze_held(self, df: pd.DataFrame) -> bool:
        """Squeeze ON for >= N consecutive days ending yesterday."""
        n = int(self.params["squeeze_min_days"])
        if len(df) < n + 2:
            return False
        recent = df["squeeze_on"].iloc[-1 - n : -1]
        return len(recent) == n and bool(recent.all())

    def conditions(self, df: pd.DataFrame) -> list[tuple[str, bool]]:
        p = self.params
        row = df.iloc[-1]
        prev_high = df.iloc[-2]["high"] if len(df) >= 2 else float("nan")
        return [
            (f"직전 {p['squeeze_min_days']}일 이상 스퀴즈 유지", self._squeeze_held(df)),
            ("스퀴즈 해제 (오늘 밴드 확장)", not bool(row.get("squeeze_on", True))),
            ("상방 돌파 (종가 > 전일 고가)", pd.notna(prev_high) and row["close"] > prev_high),
            (f"거래량 > 평소의 {p['vol_mult']}배",
             pd.notna(row["vol_ma20"]) and row["volume"] > p["vol_mult"] * row["vol_ma20"]),
            ("20일 회귀 기울기 양(+) (모멘텀)",
             pd.notna(row["linreg_slope20"]) and row["linreg_slope20"] > 0),
        ]

    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        if len(df) < int(self.params["squeeze_min_days"]) + 2:
            return None
        if not all(ok for _, ok in self.conditions(df)):
            return None
        row = df.iloc[-1]
        p = self.params
        if pd.isna(row["atr14"]):
            return None
        # Longer squeezes wind the spring tighter.
        full_streak = 0
        for on in reversed(df["squeeze_on"].iloc[:-1].tolist()):
            if not on:
                break
            full_streak += 1
        vol_ratio = float(row["volume"] / row["vol_ma20"])
        n = int(p["squeeze_min_days"])
        strength = round(
            55 + 25 * min(1.0, (full_streak - n) / 10.0) + 20 * min(1.0, (vol_ratio - p["vol_mult"]) / 2.0),
            1,
        )
        price = float(row["close"])
        squeeze_range_low = float(df["low"].iloc[-1 - full_streak : -1].min())
        return Signal(
            ticker=ticker,
            name=name,
            market=market,
            strategy_id=self.strategy_id,
            direction="BUY",
            strength=strength,
            price=price,
            signal_date=row["date"] if "date" in row else df.index[-1],
            indicators=self._snapshot(row, ["atr14", "linreg_slope20", "bb_upper", "kc_upper", "vol_ma20"]),
            suggested_stop_loss=round(squeeze_range_low, 4),  # below squeeze range low
            suggested_take_profit=None,  # ATR trailing exit
            exit_mode=self.exit_mode,
            reason=(
                f"{full_streak}일간 변동성 수축(스퀴즈) 후 상방 돌파 — "
                f"거래량 평소의 {vol_ratio:.1f}배, 모멘텀 양(+)"
            ),
        )
