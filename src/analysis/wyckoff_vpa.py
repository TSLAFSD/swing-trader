"""Wyckoff VPA engine: liquidity levels, climaxes, Weis waves, exhaustion.

Pure functions over adjusted daily OHLCV. Parameters come from
config/strategies.yaml (wyckoff_spring.params.vpa). Buy side and sell side
share one mirrored core ("방향 반전, 코드 재사용").

NO-REPAINT GUARANTEE: a pivot at bar i exists only after `pivot_strength`
candles CLOSE to its right — it is usable from bar i + pivot_strength onward,
in scans and backtests identically. Tests assert the absence of repainting.

Pivot/equal-level clustering adapted from joshyattridge/smart-money-concepts
(MIT License) — swing_highs_lows + liquidity concepts, reimplemented in
pandas/numpy (no dependency added).
"""

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BUY, SELL = 1, -1  # side constants: BUY analyses lows, SELL analyses highs


@dataclass
class LiquidityLevel:
    """A confirmed liquidity pool (equal lows for BUY side / highs for SELL)."""

    level: float
    formed_date: date
    touch_count: int
    confirmed_date: date  # date of the bar that confirmed the LAST pivot


@dataclass
class Climax:
    """Selling Climax (BUY side) or Buying Climax / UTAD (SELL side)."""

    sweep_date: date
    sweep_idx: int
    volume_ratio: float  # bar volume / VolMA
    recovery_type: str  # "close_recovery" | "rejection_wick"
    extreme: float  # climax LOW (buy side) / climax HIGH (sell side)

    @property
    def climax_low(self) -> float:
        """Spec-named accessor (buy side)."""
        return self.extreme


@dataclass
class Exhaustion:
    """Supply (buy side) / demand (sell side) exhaustion on the retest wave."""

    test_volume_ratio: float  # retest wave volume / climax wave volume
    retest_date: date


# ---------------------------------------------------------------------------
# 와이코프 원리 — 유동성 풀(liquidity pool):
# 동일 저가(equal lows)가 반복되면 그 직하단에 손절 주문이 쌓인다. 세력은
# 물량 확보를 위해 이 레벨을 의도적으로 이탈시켜 손절 물량을 흡수(스윕)한다.
# 따라서 '레벨'은 미래 정보 없이, 우측 캔들이 확정된 피벗 저점만으로 만든다.
# ---------------------------------------------------------------------------
def _confirmed_pivots(df: pd.DataFrame, strength: int, side: int) -> list[int]:
    """Indexes of pivots whose right side is fully closed (repaint-free)."""
    col = "low" if side == BUY else "high"
    values = df[col].to_numpy()
    n = len(values)
    pivots: list[int] = []
    for i in range(strength, n - strength):  # i + strength <= n-1 → confirmed
        window_left = values[i - strength : i]
        window_right = values[i + 1 : i + 1 + strength]
        if side == BUY:
            if values[i] < window_left.min() and values[i] < window_right.min():
                pivots.append(i)
        else:
            if values[i] > window_left.max() and values[i] > window_right.max():
                pivots.append(i)
    return pivots


def _detect_liquidity(
    df: pd.DataFrame, lookback: int, pivot_strength: int, equal_pct: float, side: int
) -> LiquidityLevel | None:
    pivots = [
        i for i in _confirmed_pivots(df, pivot_strength, side) if i >= len(df) - lookback
    ]
    if not pivots:
        return None
    col = "low" if side == BUY else "high"
    values = df[col].to_numpy()
    pivots = [i for i in pivots if values[i] > 0]
    if not pivots:
        return None
    # Cluster pivot prices within equal_pct of each other (touch counting).
    clusters: list[list[int]] = []
    for i in sorted(pivots, key=lambda k: values[k]):
        if values[i] <= 0:  # corrupt bar guard (zero/negative price)
            continue
        placed = False
        for cluster in clusters:
            anchor = values[cluster[0]]
            if abs(values[i] / anchor - 1) * 100 <= equal_pct:
                cluster.append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])
    # Most-touched cluster wins; tie-break: most recent pivot.
    best = max(clusters, key=lambda c: (len(c), max(c)))
    level = float(values[best].min() if side == BUY else values[best].max())
    first = min(best)
    last = max(best)
    confirm_idx = min(last + pivot_strength, len(df) - 1)
    return LiquidityLevel(
        level=level,
        formed_date=df["date"].iloc[first],
        touch_count=len(best),
        confirmed_date=df["date"].iloc[confirm_idx],
    )


def detect_liquidity_low(
    df: pd.DataFrame, lookback: int = 60, pivot_strength: int = 3, equal_low_pct: float = 0.5
) -> LiquidityLevel | None:
    """Most significant confirmed equal-low liquidity pool (buy side)."""
    return _detect_liquidity(df, lookback, pivot_strength, equal_low_pct, BUY)


def detect_liquidity_high(
    df: pd.DataFrame, lookback: int = 60, pivot_strength: int = 3, equal_high_pct: float = 0.5
) -> LiquidityLevel | None:
    """Most significant confirmed equal-high liquidity pool (sell side)."""
    return _detect_liquidity(df, lookback, pivot_strength, equal_high_pct, SELL)


# ---------------------------------------------------------------------------
# 와이코프 원리 — 셀링 클라이맥스(SC) / UTAD:
# 레벨 이탈 + 거래량 폭발은 '공급의 절정'이다. 단, 종가가 레벨 위로 회복되거나
# 긴 거부 꼬리가 남아야 흡수(absorption)의 증거가 된다. 회복 없는 이탈은
# 단순 하락 지속일 수 있으므로 클라이맥스로 보지 않는다. (매도 측은 대칭: UTAD)
# ---------------------------------------------------------------------------
def _detect_climax(
    df: pd.DataFrame, level: float, vol_ma_days: int, vol_mult: float,
    wick_body_ratio: float, side: int,
) -> Climax | None:
    vol_ma = df["volume"].rolling(vol_ma_days).mean()
    for i in range(len(df) - 1, vol_ma_days - 1, -1):  # most recent first
        row = df.iloc[i]
        ma = vol_ma.iloc[i]
        if pd.isna(ma) or ma <= 0 or row["volume"] <= vol_mult * ma:
            continue
        body = abs(row["close"] - row["open"])
        if side == BUY:
            swept = row["low"] < level
            recovered = row["close"] > level
            wick = min(row["open"], row["close"]) - row["low"]
            extreme = float(row["low"])
        else:
            swept = row["high"] > level
            recovered = row["close"] < level
            wick = row["high"] - max(row["open"], row["close"])
            extreme = float(row["high"])
        if not swept:
            continue
        rejection = body > 0 and wick >= wick_body_ratio * body
        if recovered or rejection:
            return Climax(
                sweep_date=row["date"],
                sweep_idx=i,
                volume_ratio=float(row["volume"] / ma),
                recovery_type="close_recovery" if recovered else "rejection_wick",
                extreme=extreme,
            )
    return None


def detect_selling_climax(
    df: pd.DataFrame, level: float, vol_ma_days: int = 20,
    vol_mult: float = 2.0, wick_body_ratio: float = 2.0,
) -> Climax | None:
    """Most recent Selling Climax sweeping below the liquidity-low level."""
    return _detect_climax(df, level, vol_ma_days, vol_mult, wick_body_ratio, BUY)


def detect_buying_climax(
    df: pd.DataFrame, level: float, vol_ma_days: int = 20,
    vol_mult: float = 2.0, wick_body_ratio: float = 2.0,
) -> Climax | None:
    """Most recent Buying Climax / UTAD sweeping above the liquidity-high level."""
    return _detect_climax(df, level, vol_ma_days, vol_mult, wick_body_ratio, SELL)


# ---------------------------------------------------------------------------
# 와이코프/와이스 원리 — Weis Wave:
# 가격이 zigzag_pct 이상 되돌릴 때마다 파동을 끊고, 파동 단위로 거래량을
# 누적한다(David Weis). 같은 폭의 파동이라도 누적 거래량(노력)이 줄면
# 해당 방향의 세력이 소진되고 있다는 뜻이다.
# ---------------------------------------------------------------------------
def weis_waves(df: pd.DataFrame, zigzag_pct: float = 3.0) -> pd.DataFrame:
    """Close-based zigzag waves with per-wave cumulative volume.

    Wave k covers bars (extreme_{k-1}, extreme_k]; bar 0 seeds the first
    extreme and belongs to no wave.

    Returns:
        DataFrame[wave_id, direction, start_idx, end_idx, start_date,
        end_date, start_price, end_price, cum_volume, bars, price_range].
    """
    closes = df["close"].to_numpy()
    n = len(closes)
    rows: list[dict] = []
    if n < 2:
        return pd.DataFrame(rows)
    direction = 0  # unknown until the first >=zigzag_pct move
    extreme_idx, anchor_idx = 0, 0
    threshold = zigzag_pct / 100.0

    def close_wave(end_idx: int, dir_: int) -> None:
        start_idx = anchor_idx
        seg = df.iloc[start_idx + 1 : end_idx + 1]
        rows.append(
            {
                "wave_id": len(rows) + 1,
                "direction": dir_,
                "start_idx": start_idx,
                "end_idx": end_idx,
                "start_date": df["date"].iloc[start_idx],
                "end_date": df["date"].iloc[end_idx],
                "start_price": float(closes[start_idx]),
                "end_price": float(closes[end_idx]),
                "cum_volume": float(seg["volume"].sum()),
                "bars": int(end_idx - start_idx),
                "price_range": float(abs(closes[end_idx] - closes[start_idx])),
            }
        )

    for i in range(1, n):
        price = closes[i]
        if direction == 0:
            # Bar 0 stays the anchor until the first full threshold move.
            if price >= closes[extreme_idx] * (1 + threshold):
                direction = 1
                extreme_idx = i
            elif price <= closes[extreme_idx] * (1 - threshold):
                direction = -1
                extreme_idx = i
            continue
        if direction == 1:
            if price > closes[extreme_idx]:
                extreme_idx = i
            elif price <= closes[extreme_idx] * (1 - threshold):
                close_wave(extreme_idx, 1)
                anchor_idx = extreme_idx
                direction, extreme_idx = -1, i
        else:
            if price < closes[extreme_idx]:
                extreme_idx = i
            elif price >= closes[extreme_idx] * (1 + threshold):
                close_wave(extreme_idx, -1)
                anchor_idx = extreme_idx
                direction, extreme_idx = 1, i
    if direction != 0 and extreme_idx > anchor_idx:
        close_wave(extreme_idx, direction)  # open (final) wave snapshot
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 와이코프 원리 — 공급 고갈(spring 테스트):
# 클라이맥스 후의 되돌림(리테스트)이 '현저히 적은 거래량'으로 이루어지면
# 그 가격대에 더 팔 사람이 없다는 증거다. 리테스트가 클라이맥스 저가를
# 다시 깨면 흡수 가설 자체가 무효가 된다. (매도 측은 수요 고갈로 대칭)
# ---------------------------------------------------------------------------
def _detect_exhaustion(
    waves: pd.DataFrame, climax: Climax, retest_window: int, exhaust_ratio: float, side: int
) -> Exhaustion | None:
    if waves.empty:
        return None
    against = -1 if side == BUY else 1  # wave direction that retests the level
    # A recovery-close climax bar usually STARTS the next wave, so the climax
    # wave (close-based zigzag) ends at sweep_idx or the bar just before it.
    climax_waves = waves[
        (waves["direction"] == against)
        & (waves["start_idx"] < climax.sweep_idx)
        & (waves["end_idx"] >= climax.sweep_idx - 1)
    ]
    if climax_waves.empty:
        return None
    climax_wave = climax_waves.iloc[-1]
    if climax_wave["cum_volume"] <= 0:
        return None
    retests = waves[
        (waves["direction"] == against)
        & (waves["start_idx"] > climax_wave["end_idx"])
        & (waves["start_idx"] <= climax.sweep_idx + retest_window)
    ]
    if retests.empty:
        return None
    retest = retests.iloc[0]
    # Invalidation: the retest extreme breaks beyond the climax extreme.
    if side == BUY and retest["end_price"] < climax.extreme:
        return None
    if side == SELL and retest["end_price"] > climax.extreme:
        return None
    ratio = float(retest["cum_volume"] / climax_wave["cum_volume"])
    if ratio > exhaust_ratio:
        return None
    return Exhaustion(test_volume_ratio=ratio, retest_date=retest["end_date"])


def detect_supply_exhaustion(
    waves: pd.DataFrame, climax: Climax, retest_window: int = 10, exhaust_ratio: float = 0.5
) -> Exhaustion | None:
    """Low-volume retest after a Selling Climax (buy side)."""
    return _detect_exhaustion(waves, climax, retest_window, exhaust_ratio, BUY)


def detect_demand_exhaustion(
    waves: pd.DataFrame, climax: Climax, retest_window: int = 10, exhaust_ratio: float = 0.5
) -> Exhaustion | None:
    """Low-volume retest after a Buying Climax / UTAD (sell side)."""
    return _detect_exhaustion(waves, climax, retest_window, exhaust_ratio, SELL)


def diagnose_stage_count(df: pd.DataFrame, vpa: dict) -> int:
    """How many buy-side stages (level/climax/exhaustion) are present: 0-3.

    Used by the Telegram Wyckoff badge (U4): 3=🟢 매집권, 1-2=🟡 관찰, 0=⚪.
    """
    level = detect_liquidity_low(
        df, lookback=vpa["lookback"], pivot_strength=vpa["pivot_strength"],
        equal_low_pct=vpa["equal_low_pct"],
    )
    if level is None:
        return 0
    climax = detect_selling_climax(
        df, level.level, vol_ma_days=vpa["vol_ma_days"],
        vol_mult=vpa["vol_mult"], wick_body_ratio=vpa["wick_body_ratio"],
    )
    if climax is None:
        return 1
    exhaustion = detect_supply_exhaustion(
        weis_waves(df, zigzag_pct=vpa["zigzag_pct"]), climax,
        retest_window=vpa["retest_window"], exhaust_ratio=vpa["exhaust_ratio"],
    )
    return 2 if exhaustion is None else 3


def wyckoff_badge_kr(stage_count: int) -> str:
    """Telegram badge label for a stage count."""
    if stage_count >= 3:
        return "🟢 매집권"
    if stage_count >= 1:
        return f"🟡 관찰({stage_count}/3)"
    return "⚪ 해당 없음"
