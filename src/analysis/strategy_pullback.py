"""① Pullback (눌림목): dip-buy within an established mid-term uptrend."""

import pandas as pd

from src.analysis.base_strategy import BaseStrategy, Signal
from src.analysis.registry import register
from src.risk.distribution import distribution_evidence


def _gt(a: float, b: float) -> bool:
    """NaN-safe a > b."""
    return pd.notna(a) and pd.notna(b) and a > b


@register
class PullbackStrategy(BaseStrategy):
    """Buy(ALL): close>SMA60; SMA20>SMA60; RSI14<40; ADX>20; vol>0.7xVolMA20; close<=BB mid."""

    strategy_id = "pullback"
    name_kr = "눌림목"

    def conditions(self, df: pd.DataFrame) -> list[tuple[str, bool]]:
        row = df.iloc[-1]
        p = self.params
        conds = [
            ("주가가 60일선 위 (중기 상승)", _gt(row["close"], row[f"sma{p['trend_sma']}"])),
            ("20일선이 60일선 위 (정배열)", _gt(row[f"sma{p['pull_sma']}"], row[f"sma{p['trend_sma']}"])),
            (f"RSI < {p['rsi_max']} (단기 조정)", _gt(p["rsi_max"], row["rsi14"])),
            (f"ADX > {p['adx_min']} (추세 존재)", _gt(row["adx14"], p["adx_min"])),
            (f"거래량 ≥ 평소의 {p['vol_ratio_min']}배", _gt(row["volume"], p["vol_ratio_min"] * row["vol_ma20"])),
            ("주가가 볼린저 중심선 이하 (눌림)", _gt(row["bb_mid"], row["close"]) or row["close"] == row["bb_mid"]),
        ]
        if "dist_veto_bars" in p:
            n = int(p["dist_veto_bars"])
            conds.append((
                f"최근 {n}봉 내 분산(UTAD) 징후 없음",
                distribution_evidence(df, recent_bars=n) is None,
            ))
        return conds

    def should_exit(self, df: pd.DataFrame) -> str | None:
        row = df.iloc[-1]
        p = self.params
        if pd.notna(row["rsi14"]) and row["rsi14"] > p["rsi_exit"]:
            return f"RSI {row['rsi14']:.0f} 과열 (> {p['rsi_exit']})"
        if pd.notna(row["sma20"]) and row["close"] < row["sma20"]:
            return "20일선 이탈"
        if pd.notna(row["bb_upper"]) and row["close"] >= row["bb_upper"]:
            return "볼린저 상단 도달"
        return None

    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        if not all(ok for _, ok in self.conditions(df)):
            return None
        row = df.iloc[-1]
        p = self.params
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
