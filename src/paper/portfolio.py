"""Virtual (paper) portfolio — forward out-of-sample track record (P-A).

On every CONFIRMED scan the system virtually BUYS each fresh A-grade signal at
the confirmed close and manages it through the SAME exit path the live monitor
uses (`positions.evaluate_position` -> `exit_engine.check_exit`), so the
resulting ledger is an honest paper record of "does this system make money" —
never an in-sample backtest. This is DISTINCT from:
  - the owner's real positions (config/positions.yaml), and
  - the flat signal study (signals.parquet + forward_returns).

Two stores, both riding the orphan `data` branch (publish/restore glob
*.parquet + *.json):
  - PAPER_OPEN_FILE   (JSON)    mutable list of currently-held virtual positions.
  - PAPER_TRADES_FILE (Parquet) append-only closed-trade ledger = labeled
                                dataset (entry features + realized outcome/row).

Capital model (deliberately simple for P-A): each trade gets a fixed notional
(PAPER_START_EQUITY * PAPER_TRADE_FRACTION); MAX_POSITION_SLOTS caps concurrent
exposure. US and KR share one notional pool measured in RETURN space — no FX
conversion (return_pct is currency-free; absolute pnl is in abstract notional
units). Equity curve / stats are derived later (P-B).

Units mirror risk/trade_ledger.py so P-B can reuse discipline_summary_kr:
return_pct / mae_pct / mfe_pct are PERCENT; holding_days is CALENDAR days.
"""

import json
import logging
import math
import uuid
from datetime import date

import pandas as pd

from config import settings
from src.analysis.indicators import compute_indicators
from src.risk.positions import Position, evaluate_position

logger = logging.getLogger(__name__)

TRADES_COLUMNS = [
    "trade_id", "signal_date", "entry_date", "ticker", "market", "strategy_id",
    "grade", "grade_value", "strength", "confidence", "regime_factor",
    "entry_rule", "entry_price", "entry_fill", "shares", "cash_allocated",
    "stop_loss", "take_profit", "exit_mode",
    "exit_date", "exit_price", "exit_fill", "exit_reason",
    "holding_days", "return_pct", "pnl", "mae_pct", "mfe_pct",
    "features_json", "rationale_kr", "exit_rationale_kr", "schema_version",
]


# --- helpers -------------------------------------------------------------

def _cost_fraction() -> float:
    """One-way cost (slippage + fee) as a fraction, e.g. 0.0005 for 5 bps."""
    return (settings.PAPER_SLIPPAGE_BPS + settings.PAPER_FEE_BPS) / 10_000.0


def _clean_features(indicators: dict | None) -> dict[str, float]:
    """Entry-time indicator snapshot, finite floats only (NaN/inf dropped)."""
    out: dict[str, float] = {}
    for key, value in (indicators or {}).items():
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(num):
            out[str(key)] = num
    return out


def _rationale_kr(sig) -> str:
    """Short Korean 'why we bought' line for the journal/ledger."""
    gv = f"{sig.grade_value:.0f}" if sig.grade_value is not None else "—"
    cf = f"{sig.confidence:.2f}" if sig.confidence is not None else "—"
    return f"{sig.grade}등급(점수 {gv}) · {sig.strategy_id} · 강도 {sig.strength:.0f} · 신뢰도 {cf}"


def _exit_reason_code(reason: str) -> str:
    """Map the engine's Korean exit reason to a stable category code.

    Order matters: the ATR-trailing reason contains '손절', so check it first.
    """
    if "ATR 추적" in reason:
        return "trailing"
    if "손절" in reason:
        return "stop"
    if "목표가" in reason or "ROI" in reason:
        return "take_profit"
    if "보유기간" in reason or "타임스톱" in reason:
        return "time_stop"
    return "other"


def _load_open(path) -> list[dict]:
    """Load open virtual positions (empty list when missing/unreadable)."""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")) or []
    except (json.JSONDecodeError, OSError):
        logger.exception("paper: %s unreadable — starting empty", path)
        return []


def _save_open(rows: list[dict], path) -> None:
    """Persist open virtual positions as JSON (rides the data branch)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def load_trades(path=None) -> pd.DataFrame:
    """Load the closed virtual-trade ledger (empty frame when none)."""
    path = path or settings.PAPER_TRADES_FILE
    if not path.exists():
        return pd.DataFrame(columns=TRADES_COLUMNS)
    return pd.read_parquet(path)


def load_open(path=None) -> list[dict]:
    """Load currently-held virtual positions (public; empty list when none)."""
    return _load_open(path or settings.PAPER_OPEN_FILE)


def _append_trades(records: list[dict], path) -> int:
    """Append closed-trade records to the ledger (deduped on trade_id)."""
    rows = pd.DataFrame(records, columns=TRADES_COLUMNS)
    if path.exists():
        rows = pd.concat([pd.read_parquet(path), rows], ignore_index=True)
    rows = rows.drop_duplicates(subset=["trade_id"], keep="last")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_parquet(path, compression="zstd", index=False)
    logger.info("paper: %d closed trade(s) recorded (%d total)", len(records), len(rows))
    return len(rows)


def _indicator_frame(data: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Per-ticker indicator frame from the market store slice (None if empty)."""
    if data.empty:
        return None
    tdf = data[data["ticker"] == ticker].sort_values("date").reset_index(drop=True)
    if tdf.empty:
        return None
    try:
        return compute_indicators(tdf)
    except Exception:  # short/degenerate series — skip this position this scan
        logger.exception("paper: indicator computation failed for %s", ticker)
        return None


def _since_entry(ind: pd.DataFrame, entry_date: date) -> pd.DataFrame:
    """Rows from entry_date onward (inclusive)."""
    return ind[pd.to_datetime(ind["date"]).dt.date >= entry_date]


# --- core transitions ----------------------------------------------------

def _open_position(sig, market: str) -> dict:
    """Build an open-position record for a fresh A-grade signal (buy at close)."""
    cost = _cost_fraction()
    entry_price = float(sig.price)
    entry_fill = round(entry_price * (1 + cost), 6)
    cash = settings.PAPER_START_EQUITY * settings.PAPER_TRADE_FRACTION
    shares = round(cash / entry_fill, 6) if entry_fill > 0 else 0.0
    entry_date = str(sig.signal_date)
    return {
        "trade_id": uuid.uuid4().hex,
        "signal_date": str(sig.signal_date),
        "entry_date": entry_date,
        "ticker": sig.ticker,
        "market": market,
        "strategy_id": sig.strategy_id,
        "grade": sig.grade,
        "grade_value": sig.grade_value,
        "strength": sig.strength,
        "confidence": sig.confidence,
        "regime_factor": sig.regime_factor,
        "entry_rule": "close",
        "entry_price": entry_price,
        "entry_fill": entry_fill,
        "shares": shares,
        "cash_allocated": cash,
        "stop_loss": sig.suggested_stop_loss,
        "take_profit": sig.suggested_take_profit,
        "exit_mode": sig.exit_mode,
        "peak_close": entry_price,
        "mae_pct": 0.0,
        "mfe_pct": 0.0,
        "last_mark_date": entry_date,
        "last_close": entry_price,
        "unrealized_pct": 0.0,
        "rationale_kr": _rationale_kr(sig),
        "features": _clean_features(sig.indicators),
        "schema_version": settings.PAPER_SCHEMA_VERSION,
    }


def _mark(row: dict, since: pd.DataFrame) -> dict:
    """Mark an open position to the latest bar (peak/MAE/MFE/unrealized)."""
    entry_price = row["entry_price"]
    last = since.iloc[-1]
    peak = float(since["close"].max())
    if row.get("peak_close") is not None:
        peak = max(peak, float(row["peak_close"]))  # never regress on restatement
    row["peak_close"] = round(peak, 6)
    row["last_close"] = round(float(last["close"]), 6)
    row["last_mark_date"] = str(pd.to_datetime(last["date"]).date())
    row["mfe_pct"] = round((float(since["high"].max()) / entry_price - 1) * 100, 4)
    row["mae_pct"] = round((float(since["low"].min()) / entry_price - 1) * 100, 4)
    row["unrealized_pct"] = round((row["last_close"] / entry_price - 1) * 100, 4)
    return row


def _close(row: dict, since: pd.DataFrame, reason: str) -> dict:
    """Build the closed-trade record for a position the exit engine flagged."""
    cost = _cost_fraction()
    entry_price = row["entry_price"]
    entry_fill = row["entry_fill"]
    last = since.iloc[-1]
    exit_price = float(last["close"])
    exit_fill = round(exit_price * (1 - cost), 6)
    ret = (exit_fill / entry_fill - 1) if entry_fill > 0 else 0.0
    entry_date = date.fromisoformat(row["entry_date"])
    exit_date = pd.to_datetime(last["date"]).date()
    return {
        "trade_id": row["trade_id"],
        "signal_date": row["signal_date"],
        "entry_date": row["entry_date"],
        "ticker": row["ticker"],
        "market": row["market"],
        "strategy_id": row["strategy_id"],
        "grade": row["grade"],
        "grade_value": row["grade_value"],
        "strength": row["strength"],
        "confidence": row["confidence"],
        "regime_factor": row["regime_factor"],
        "entry_rule": row["entry_rule"],
        "entry_price": entry_price,
        "entry_fill": entry_fill,
        "shares": row["shares"],
        "cash_allocated": row["cash_allocated"],
        "stop_loss": row["stop_loss"],
        "take_profit": row["take_profit"],
        "exit_mode": row["exit_mode"],
        "exit_date": str(exit_date),
        "exit_price": exit_price,
        "exit_fill": exit_fill,
        "exit_reason": _exit_reason_code(reason),
        "holding_days": (exit_date - entry_date).days,
        "return_pct": round(ret * 100, 2),
        "pnl": round(row["cash_allocated"] * ret, 4),
        "mae_pct": round((float(since["low"].min()) / entry_price - 1) * 100, 4),
        "mfe_pct": round((float(since["high"].max()) / entry_price - 1) * 100, 4),
        "features_json": json.dumps(row.get("features") or {}, ensure_ascii=False, sort_keys=True),
        "rationale_kr": row.get("rationale_kr", ""),
        "exit_rationale_kr": reason,
        "schema_version": settings.PAPER_SCHEMA_VERSION,
    }


def _exit_reason_for(row: dict, ind: pd.DataFrame) -> str | None:
    """Engine-level exit decision via the SAME path as the live monitor."""
    pos = Position(
        ticker=row["ticker"],
        market=row["market"],
        entry_date=date.fromisoformat(row["entry_date"]),
        entry_price=row["entry_price"],
        quantity=row["shares"],
        stop_loss=row["stop_loss"],
        take_profit=row["take_profit"],
        exit_mode=row["exit_mode"],
        highest_close=row.get("peak_close"),
    )
    reason, _ = evaluate_position(pos, ind)
    return reason


# --- public entry point --------------------------------------------------

def update_paper_portfolio(market: str, signals, store, *, open_path=None, trades_path=None) -> dict:
    """Run one confirmed-scan update of the virtual portfolio for `market`.

    Exits this market's open positions through the live exit path, then opens
    fresh A-grade signals (buy at confirmed close) up to the slot cap.

    Args:
        market: "us" | "kr" (the market just scanned).
        signals: Ranked, send-filtered signals for this market (Signal objects).
        store: ParquetStore for price lookups (exit eval + MAE/MFE).
        open_path / trades_path: Overrides (tests); default to settings.

    Returns:
        Summary dict: {n_opened, closed (records), open_total, trades_total}.
    """
    summary = {"n_opened": 0, "closed": [], "open_total": 0, "trades_total": 0}
    if not settings.PAPER_ENABLED:
        return summary
    open_path = open_path or settings.PAPER_OPEN_FILE
    trades_path = trades_path or settings.PAPER_TRADES_FILE

    open_rows = _load_open(open_path)
    data = store.load(market)
    if not data.empty:
        data = data.copy()
        data["date"] = pd.to_datetime(data["date"]).dt.date

    # 1) EXIT: evaluate this market's open positions (other markets untouched —
    #    they are evaluated on their own scan).
    closed_records: list[dict] = []
    survivors: list[dict] = []
    for row in open_rows:
        if row.get("market") != market:
            survivors.append(row)
            continue
        ind = _indicator_frame(data, row["ticker"])
        if ind is None:
            survivors.append(row)
            continue
        since = _since_entry(ind, date.fromisoformat(row["entry_date"]))
        if since.empty:
            survivors.append(row)
            continue
        reason = None
        try:
            reason = _exit_reason_for(row, ind)
        except Exception:
            logger.exception("paper: exit check failed for %s", row["ticker"])
        if reason:
            closed_records.append(_close(row, since, reason))
        else:
            survivors.append(_mark(row, since))

    # 2) ENTRY: fresh A-grade signals not already held, capped at the slot limit
    #    (capital-level: count is across BOTH markets, like live positions).
    held = {r["ticker"] for r in survivors}
    used = len(survivors)
    for sig in signals:
        if used >= settings.MAX_POSITION_SLOTS:
            break
        if sig.grade not in settings.PAPER_GRADES:
            continue
        if sig.market != market or sig.ticker in held:
            continue
        survivors.append(_open_position(sig, market))
        held.add(sig.ticker)
        used += 1
        summary["n_opened"] += 1

    _save_open(survivors, open_path)
    if closed_records:
        summary["trades_total"] = _append_trades(closed_records, trades_path)
    summary["closed"] = closed_records
    summary["open_total"] = len(survivors)
    return summary
