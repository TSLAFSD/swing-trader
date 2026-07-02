"""Live signal tracking (spec §7 Layer 3).

Every emitted signal is persisted (Parquet, rides the data branch). The
weekly job computes realized +5d/+10d forward returns against stored closes,
feeds the per-strategy circuit breaker, and renders a Korean summary.
"""

import json
import logging
import math
from datetime import date
from pathlib import Path

import pandas as pd

from config import settings
from src.analysis.base_strategy import Signal
from src.data.store import ParquetStore

logger = logging.getLogger(__name__)

SIGNALS_FILE = settings.DATA_ROOT / "signals" / "signals.parquet"

COLUMNS = [
    "signal_date", "ticker", "market", "strategy_id", "strength", "price",
    "stop_loss", "take_profit", "entry_zone_top",
    # P-A: turn the signal log into a labeled dataset — the grade/confidence/
    # regime context plus the entry-time indicator snapshot (features) behind
    # each recommendation. forward_returns() supplies the labels. Old rows keep
    # NaN here (backward compatible).
    "grade", "grade_value", "confidence", "regime_factor", "features_json",
]


def _features_json(indicators: dict | None) -> str:
    """Serialize a Signal.indicators snapshot to a compact JSON string.

    numpy scalars are coerced to float; non-finite values (NaN/inf — invalid
    JSON) become null so the row stays machine-readable.
    """
    out: dict[str, float | None] = {}
    for key, value in (indicators or {}).items():
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        out[str(key)] = num if math.isfinite(num) else None
    return json.dumps(out, ensure_ascii=False, sort_keys=True)


def record_signals(signals: list[Signal], path: Path | None = None) -> int:
    """Append scan signals to the persistent log (deduped per ticker/strategy/day).

    Returns:
        Total rows now stored.
    """
    path = path or SIGNALS_FILE
    rows = pd.DataFrame(
        [
            {
                "signal_date": s.signal_date,
                "ticker": s.ticker,
                "market": s.market,
                "strategy_id": s.strategy_id,
                "strength": s.strength,
                "price": s.price,
                "stop_loss": s.suggested_stop_loss,
                "take_profit": s.suggested_take_profit,
                "entry_zone_top": s.entry_zone_top,
                "grade": s.grade,
                "grade_value": s.grade_value,
                "confidence": s.confidence,
                "regime_factor": s.regime_factor,
                "features_json": _features_json(s.indicators),
            }
            for s in signals
        ],
        columns=COLUMNS,
    )
    if path.exists():
        rows = pd.concat([pd.read_parquet(path), rows], ignore_index=True)
    rows = rows.drop_duplicates(subset=["signal_date", "ticker", "strategy_id"], keep="first")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_parquet(path, compression="zstd", index=False)
    logger.info("tracker: %d signals stored", len(rows))
    return len(rows)


def load_signals(path: Path | None = None) -> pd.DataFrame:
    """Load the signal log (empty frame when none)."""
    path = path or SIGNALS_FILE
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_parquet(path)


def forward_returns(
    store: ParquetStore, signals: pd.DataFrame, horizons: tuple[int, ...] = (5, 10)
) -> pd.DataFrame:
    """Compute realized +Nd forward returns for each logged signal.

    A horizon column stays NaN until enough trading days have elapsed.

    Args:
        store: Market-data store (close prices).
        signals: load_signals() output.
        horizons: Trading-day horizons.

    Returns:
        signals + fwd_{n}d columns (fractions).
    """
    out = signals.copy()
    for n in horizons:
        out[f"fwd_{n}d"] = float("nan")
    for market in out["market"].unique():
        data = store.load(market)
        if data.empty:
            continue
        closes = data.pivot_table(index="date", columns="ticker", values="close")
        closes.index = pd.to_datetime(closes.index)
        trading_days = closes.index
        for i, row in out[out["market"] == market].iterrows():
            t = row["ticker"]
            if t not in closes.columns:
                continue
            sig_day = pd.Timestamp(row["signal_date"])
            pos = trading_days.searchsorted(sig_day)
            if pos >= len(trading_days) or trading_days[pos] != sig_day:
                continue
            base = closes[t].iloc[pos]
            for n in horizons:
                if pos + n < len(trading_days):
                    fwd = closes[t].iloc[pos + n]
                    if pd.notna(base) and pd.notna(fwd) and base > 0:
                        out.loc[i, f"fwd_{n}d"] = float(fwd / base - 1.0)
    return out


def trailing_stats(fwd: pd.DataFrame, strategy_id: str, n: int) -> dict:
    """Realized trailing-window stats for one strategy (adaptive Lever 1).

    Reads ONLY already-realized +10d outcomes (never fresh price). Over the last
    ``n`` signals with a realized +10d return:

    Returns:
        {n_realized, mean_fwd10, win_rate, profit_factor}. win_rate/
        profit_factor are None when no realized outcomes exist; profit_factor is
        inf when there are wins but no losing trades.
    """
    empty = {"n_realized": 0, "mean_fwd10": None, "win_rate": None, "profit_factor": None}
    if fwd is None or fwd.empty or "strategy_id" not in fwd.columns or "fwd_10d" not in fwd.columns:
        return empty
    grp = fwd[fwd["strategy_id"] == strategy_id].sort_values("signal_date")
    # Realized filter BEFORE tail(n): the freshest signals are always still
    # NaN (+10d not elapsed) and would otherwise mask every realized outcome
    # (2026-07-02 regression: breaker state stuck at mean_fwd10=null).
    realized = pd.to_numeric(grp["fwd_10d"], errors="coerce").dropna().tail(n)
    if realized.empty:
        return empty
    wins = float((realized > 0).sum())
    gross_win = float(realized[realized > 0].sum())
    gross_loss = float(-realized[realized <= 0].sum())
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if wins else 0.0)
    return {
        "n_realized": int(len(realized)),
        "mean_fwd10": float(realized.mean()),
        "win_rate": wins / len(realized),
        "profit_factor": profit_factor,
    }


def weekly_summary_kr(fwd: pd.DataFrame, weeks: int = 4) -> str:
    """Korean per-strategy hit-rate summary over the trailing weeks."""
    if fwd.empty:
        return "최근 시그널 기록 없음"
    cutoff = pd.Timestamp(date.today()) - pd.Timedelta(weeks=weeks)
    recent = fwd[pd.to_datetime(fwd["signal_date"]) >= cutoff]
    if recent.empty:
        return f"지난 {weeks}주간 시그널 없음"
    lines = [f"📊 지난 {weeks}주 시그널 실전 적중률"]
    for sid, grp in recent.groupby("strategy_id"):
        n = len(grp)
        f5 = grp["fwd_5d"].dropna()
        f10 = grp["fwd_10d"].dropna()
        part5 = f"+5d 평균 {f5.mean() * 100:+.1f}% (적중 {(f5 > 0).mean() * 100:.0f}%)" if len(f5) else "+5d 집계 대기"
        part10 = f"+10d 평균 {f10.mean() * 100:+.1f}% (적중 {(f10 > 0).mean() * 100:.0f}%)" if len(f10) else "+10d 집계 대기"
        lines.append(f"· {sid}: {n}건 — {part5} · {part10}")
    return "\n".join(lines)
