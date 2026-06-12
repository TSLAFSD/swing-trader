"""⑥ Wyckoff Spring (와이코프 스프링) — U3: VPA 3-stage entry.

BUY = confirmed liquidity low AND Selling Climax AND supply exhaustion AND
bullish close, all repaint-free (src/analysis/wyckoff_vpa.py). The same
pipeline feeds conditions() (checklist) and evaluate() (signal) — and the
backtesting adapter replays evaluate() per bar prefix, so scan and backtest
can never diverge.
"""

from dataclasses import dataclass

import pandas as pd

from src.analysis.base_strategy import BaseStrategy, Signal
from src.analysis.registry import register
from src.analysis.wyckoff_vpa import (
    Climax,
    Exhaustion,
    LiquidityLevel,
    detect_liquidity_low,
    detect_selling_climax,
    detect_supply_exhaustion,
    weis_waves,
)


@dataclass
class _Pipeline:
    """Point-in-time VPA stage results for the frame's last bar."""

    level: LiquidityLevel | None = None
    climax: Climax | None = None
    exhaustion: Exhaustion | None = None
    fresh: bool = False
    bullish_close: bool = False


@register
class WyckoffSpringStrategy(BaseStrategy):
    """Buy(ALL): liquidity low; selling climax; supply exhaustion; bullish close."""

    strategy_id = "wyckoff_spring"
    name_kr = "와이코프 스프링"

    def _run_pipeline(self, df: pd.DataFrame) -> _Pipeline:
        vpa = self.params["vpa"]
        result = _Pipeline()
        if len(df) < self.min_bars:
            return result
        result.level = detect_liquidity_low(
            df, lookback=vpa["lookback"], pivot_strength=vpa["pivot_strength"],
            equal_low_pct=vpa["equal_low_pct"],
        )
        if result.level is None:
            return result
        result.climax = detect_selling_climax(
            df, result.level.level, vol_ma_days=vpa["vol_ma_days"],
            vol_mult=vpa["vol_mult"], wick_body_ratio=vpa["wick_body_ratio"],
        )
        if result.climax is None:
            return result
        waves = weis_waves(df, zigzag_pct=vpa["zigzag_pct"])
        result.exhaustion = detect_supply_exhaustion(
            waves, result.climax, retest_window=vpa["retest_window"],
            exhaust_ratio=vpa["exhaust_ratio"],
        )
        if result.exhaustion is None:
            return result
        retest_pos = df.index[df["date"] == result.exhaustion.retest_date]
        if len(retest_pos):
            result.fresh = (len(df) - 1 - retest_pos[0]) <= vpa["signal_window"]
        row, prev = df.iloc[-1], df.iloc[-2]
        result.bullish_close = bool(row["close"] > row["open"] or row["close"] > prev["close"])
        return result

    def conditions(self, df: pd.DataFrame) -> list[tuple[str, bool]]:
        p = self._run_pipeline(df)
        vpa = self.params["vpa"]
        return [
            ("유동성 저점 확정 (동일 저가 군집)", p.level is not None),
            (f"셀링 클라이맥스 (거래량 ≥ {vpa['vol_mult']}배 + 회복)", p.climax is not None),
            (f"공급 고갈 (리테스트 거래량 ≤ {vpa['exhaust_ratio']:.0%})", p.exhaustion is not None),
            (f"신호 창 내 ({vpa['signal_window']}봉)", p.fresh),
            ("상승 마감", p.bullish_close),
        ]

    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        if len(df) < self.min_bars:
            return None
        p = self._run_pipeline(df)
        if not (p.level and p.climax and p.exhaustion and p.fresh and p.bullish_close):
            return None
        row = df.iloc[-1]
        if pd.isna(row["atr14"]):
            return None
        # Continuous strength: climax effort x how dry the retest was (spec C-1).
        score = p.climax.volume_ratio * (1.0 - p.exhaustion.test_volume_ratio)
        strength = round(min(100.0, 40.0 + 25.0 * score), 1)
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
            indicators=self._snapshot(row, ["atr14", "vol_ma20", "zscore20"])
            | {
                "liquidity_level": round(p.level.level, 4),
                "climax_volume_ratio": round(p.climax.volume_ratio, 2),
                "retest_volume_ratio": round(p.exhaustion.test_volume_ratio, 3),
            },
            suggested_stop_loss=round(p.climax.climax_low * 0.995, 4),  # below climax low
            suggested_take_profit=None,  # ATR trailing exit
            exit_mode=self.exit_mode,
            reason=(
                f"유동성 저점 {p.level.level:,.0f}({p.level.touch_count}회 터치) 이탈 후 "
                f"셀링 클라이맥스(거래량 {p.climax.volume_ratio:.1f}배, {p.climax.sweep_date}) — "
                f"리테스트 거래량 {p.exhaustion.test_volume_ratio:.0%}로 공급 고갈, 스프링 완성"
            ),
        )
