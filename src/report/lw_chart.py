"""lightweight-charts v5 data preparation (U5/E-1).

ALL computation happens here in Python — daily + weekly series, Weis wave
histogram, Wyckoff event markers, price lines — serialized to JSON; the
template's JS only renders. Weekly bars are resampled from our own daily
data (no extra fetching).
"""

import logging
from typing import Any

import pandas as pd
import pandas_ta as ta

from src.analysis.base_strategy import Signal, load_strategy_config
from src.analysis.wyckoff_vpa import (
    detect_liquidity_low,
    detect_selling_climax,
    detect_supply_exhaustion,
    weis_waves,
)

logger = logging.getLogger(__name__)

_UP, _DOWN = "#26a69a", "#ef5350"


def _ts(d: Any) -> str:
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def _line(df: pd.DataFrame, col: str) -> list[dict]:
    out = []
    for d, v in zip(df["date"], df[col]):
        if v == v:  # NaN-safe
            out.append({"time": _ts(d), "value": round(float(v), 6)})
    return out


def _candles(df: pd.DataFrame) -> list[dict]:
    out = []
    for row in df.itertuples():
        if row.close != row.close:
            continue
        out.append(
            {
                "time": _ts(row.date), "open": round(float(row.open), 6),
                "high": round(float(row.high), 6), "low": round(float(row.low), 6),
                "close": round(float(row.close), 6),
            }
        )
    return out


def _volume(df: pd.DataFrame) -> list[dict]:
    out = []
    for row in df.itertuples():
        color = _UP if row.close >= row.open else _DOWN
        out.append({"time": _ts(row.date), "value": float(row.volume), "color": color + "66"})
    return out


def _macd_frame(close: pd.Series) -> pd.DataFrame | None:
    macd = ta.macd(close)
    if macd is None:
        return None
    macd.columns = [str(c) for c in macd.columns]
    cols = {c: name for c in macd.columns
            for prefix, name in (("MACD_", "macd"), ("MACDs_", "signal"), ("MACDh_", "hist"))
            if c.startswith(prefix)}
    return macd.rename(columns=cols)


def _weis_histogram(df: pd.DataFrame, zigzag_pct: float) -> list[dict]:
    """Per-bar running cumulative volume within each Weis wave, direction-colored."""
    waves = weis_waves(df, zigzag_pct=zigzag_pct)
    out = []
    for wave in waves.itertuples():
        seg = df.iloc[int(wave.start_idx) + 1 : int(wave.end_idx) + 1]
        running = 0.0
        color = _UP if wave.direction == 1 else _DOWN
        for row in seg.itertuples():
            running += float(row.volume)
            out.append({"time": _ts(row.date), "value": running, "color": color})
    return out


def _timeframe_payload(df: pd.DataFrame, zigzag_pct: float, sma_lengths: tuple[int, ...]) -> dict:
    """Series bundle for one timeframe (daily or weekly)."""
    close = df["close"]
    payload: dict[str, Any] = {
        "candles": _candles(df),
        "volume": _volume(df),
        "rsi": [],
        "macd": [], "macd_signal": [], "macd_hist": [],
        "weis": _weis_histogram(df, zigzag_pct),
        "smas": {},
        "bb_upper": [], "bb_lower": [],
    }
    for n in sma_lengths:
        sma = ta.sma(close, length=n)
        if sma is not None:
            payload["smas"][f"SMA{n}"] = _line(df.assign(_v=sma), "_v")
    rsi = ta.rsi(close, length=14)
    if rsi is not None:
        payload["rsi"] = _line(df.assign(_v=rsi), "_v")
    macd = _macd_frame(close)
    if macd is not None:
        payload["macd"] = _line(df.assign(_v=macd["macd"]), "_v")
        payload["macd_signal"] = _line(df.assign(_v=macd["signal"]), "_v")
        hist = []
        for d, v in zip(df["date"], macd["hist"]):
            if v == v:
                hist.append({"time": _ts(d), "value": round(float(v), 6),
                             "color": _UP if v >= 0 else _DOWN})
        payload["macd_hist"] = hist
    bb = ta.bbands(close, length=20, std=2)
    if bb is not None:
        for col in bb.columns:
            name = str(col)
            if name.startswith("BBU_"):
                payload["bb_upper"] = _line(df.assign(_v=bb[col]), "_v")
            elif name.startswith("BBL_"):
                payload["bb_lower"] = _line(df.assign(_v=bb[col]), "_v")
    return payload


def _weekly_frame(df: pd.DataFrame) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(df["date"]))
    w = (
        df.set_index(idx)
        .resample("W-FRI")
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
             close=("close", "last"), volume=("volume", "sum"))
        .dropna()
    )
    w.index.name = "date"
    w = w.reset_index()
    w["date"] = w["date"].dt.date
    return w


def _vpa_events(df: pd.DataFrame, vpa: dict) -> dict:
    """Point-in-time buy-side stage objects (markers + diagnosis share this)."""
    level = detect_liquidity_low(
        df, lookback=vpa["lookback"], pivot_strength=vpa["pivot_strength"],
        equal_low_pct=vpa["equal_low_pct"],
    )
    climax = exhaustion = None
    if level is not None:
        climax = detect_selling_climax(
            df, level.level, vol_ma_days=vpa["vol_ma_days"],
            vol_mult=vpa["vol_mult"], wick_body_ratio=vpa["wick_body_ratio"],
        )
        if climax is not None:
            exhaustion = detect_supply_exhaustion(
                weis_waves(df, zigzag_pct=vpa["zigzag_pct"]), climax,
                retest_window=vpa["retest_window"], exhaust_ratio=vpa["exhaust_ratio"],
            )
    return {"level": level, "climax": climax, "exhaustion": exhaustion}


def vpa_diagnosis(df: pd.DataFrame, weekly: pd.DataFrame) -> dict:
    """🧭 Wyckoff VPA 진단 section data: 3-stage checklist + weekly context."""
    vpa = load_strategy_config()["strategies"]["wyckoff_spring"]["params"]["vpa"]
    ev = _vpa_events(df, vpa)
    level, climax, exhaustion = ev["level"], ev["climax"], ev["exhaustion"]
    stages = [
        {
            "label": "1단계 · 유동성 저점 (동일 저가 군집)",
            "ok": level is not None,
            "value": f"{level.level:,.0f} · {level.touch_count}회 터치" if level else "미확인",
        },
        {
            "label": "2단계 · 셀링 클라이맥스 (이탈+거래량 폭발+회복)",
            "ok": climax is not None,
            "value": (
                f"{climax.sweep_date} · 거래량 {climax.volume_ratio:.1f}배 · "
                + ("종가 회복" if climax.recovery_type == "close_recovery" else "꼬리 거부")
            ) if climax else "미확인",
        },
        {
            "label": "3단계 · 공급 고갈 (저거래량 리테스트)",
            "ok": exhaustion is not None,
            "value": f"리테스트 거래량 = 클라이맥스의 {exhaustion.test_volume_ratio:.0%}" if exhaustion else "미확인",
        },
    ]
    context = weekly_context_kr(weekly)
    return {"stages": stages, "weekly_context": context, "events": ev}


def weekly_context_kr(weekly: pd.DataFrame) -> str:
    """One-line weekly-structure context for the diagnosis section."""
    if len(weekly) < 20:
        return "주봉 이력 부족 — 컨텍스트 판단 불가"
    close = float(weekly["close"].iloc[-1])
    sma20w = float(weekly["close"].rolling(20).mean().iloc[-1])
    recent = weekly.tail(52)
    lo, hi = float(recent["low"].min()), float(recent["high"].max())
    pos = (close - lo) / (hi - lo) * 100 if hi > lo else float("nan")
    trend = "20주선 위" if close > sma20w else "20주선 아래"
    if pos == pos and pos <= 35:
        zone = "주봉 박스권 하단 — 매집 가설 부합"
    elif pos == pos and pos >= 75:
        zone = "주봉 레인지 상단 — 분산 가능성 유의"
    else:
        zone = "주봉 레인지 중단"
    return f"{zone} ({trend}, 52주 레인지 {pos:.0f}% 위치)"


def weekly_lines_kr(weekly: pd.DataFrame) -> list[str]:
    """2-3 weekly sentences appended to the 지표 해설 section."""
    if len(weekly) < 21:
        return []
    close = float(weekly["close"].iloc[-1])
    sma20w = float(weekly["close"].rolling(20).mean().iloc[-1])
    lines = [
        f"주봉 기준 주가가 20주선({sma20w:,.0f}) {'위 — 큰 추세 상승' if close > sma20w else '아래 — 큰 추세 하락'}"
    ]
    chg13 = (close / float(weekly["close"].iloc[-14]) - 1) * 100
    lines.append(f"최근 13주(약 3개월) 수익률 {chg13:+.1f}%")
    vol_ratio = float(weekly["volume"].iloc[-1]) / max(float(weekly["volume"].tail(20).mean()), 1.0)
    if vol_ratio == vol_ratio:
        lines.append(f"이번 주 거래량은 20주 평균의 {vol_ratio:.1f}배")
    return lines


def prepare_chart_payload(df_ind: pd.DataFrame, signal: Signal) -> dict:
    """Full JSON-serializable chart payload for the template.

    Args:
        df_ind: compute_indicators() frame (raw OHLCV columns included).
        signal: Enriched signal (price lines / BUY marker / zone).
    """
    vpa = load_strategy_config()["strategies"]["wyckoff_spring"]["params"]["vpa"]
    daily = df_ind[["date", "open", "high", "low", "close", "volume"]].copy()
    weekly = _weekly_frame(daily)

    payload = {
        "daily": _timeframe_payload(daily, vpa["zigzag_pct"], (20, 60, 200)),
        "weekly": _timeframe_payload(weekly, vpa["zigzag_pct"], (20,)),
        "priceLines": [],
        "markers": [],
    }
    if signal.price:
        payload["priceLines"].append(
            {"price": float(signal.price), "title": "제안 매수가", "color": "#4fc3f7", "dashed": False}
        )
    if signal.entry_zone_top:
        payload["priceLines"].append(
            {"price": float(signal.entry_zone_top), "title": "범위 상단", "color": "#8ab4f8", "dashed": True}
        )
    if signal.suggested_stop_loss:
        payload["priceLines"].append(
            {"price": float(signal.suggested_stop_loss), "title": "제안 손절", "color": "#ef5350", "dashed": False}
        )
    payload["markers"].append(
        {"time": _ts(signal.signal_date), "position": "belowBar", "shape": "arrowUp",
         "color": _UP, "text": "BUY"}
    )
    ev = _vpa_events(daily, vpa)
    if ev["climax"] is not None:
        payload["markers"].append(
            {"time": _ts(ev["climax"].sweep_date), "position": "belowBar", "shape": "circle",
             "color": "#ffd54f", "text": "SC/스프링"}
        )
    if ev["exhaustion"] is not None:
        payload["markers"].append(
            {"time": _ts(ev["exhaustion"].retest_date), "position": "belowBar", "shape": "circle",
             "color": "#ba68c8", "text": "리테스트"}
        )
    payload["markers"].sort(key=lambda m: m["time"])
    return payload
