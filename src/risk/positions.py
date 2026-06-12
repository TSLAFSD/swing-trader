"""Position loading + per-scan exit evaluation (spec §8).

The loader is source-swappable by design (positions.yaml today, private gist
later) — consumers only see load_positions(). Confirmed scans evaluate every
held position against its exit engine mode + the strategy sell conditions.
"""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from config import settings
from src.risk import exit_engine

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """One open position from positions.yaml."""

    ticker: str
    market: str
    entry_date: date
    entry_price: float
    quantity: float
    stop_loss: float | None
    take_profit: float | None
    exit_mode: str = "fixed"
    # U7/G-1: persisted ATR-trailing state (None until first confirmed scan).
    highest_close: float | None = None
    current_trailing_sl: float | None = None


def load_positions(path: Path | None = None) -> list[Position]:
    """Load open positions (empty list when file missing/empty)."""
    path = path or settings.POSITIONS_FILE
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for row in raw.get("positions") or []:
        out.append(
            Position(
                ticker=str(row["ticker"]),
                market=row["market"],
                entry_date=row["entry_date"] if isinstance(row["entry_date"], date) else date.fromisoformat(str(row["entry_date"])),
                entry_price=float(row["entry_price"]),
                quantity=float(row["quantity"]),
                stop_loss=None if row.get("stop_loss") is None else float(row["stop_loss"]),
                take_profit=None if row.get("take_profit") is None else float(row["take_profit"]),
                exit_mode=row.get("exit_mode", "fixed"),
                highest_close=None if row.get("highest_close") is None else float(row["highest_close"]),
                current_trailing_sl=None if row.get("current_trailing_sl") is None else float(row["current_trailing_sl"]),
            )
        )
    return out


def save_positions(positions: list[Position], path: Path | None = None) -> None:
    """Write positions.yaml (single source of truth; schema comment retained)."""
    path = path or settings.POSITIONS_FILE
    rows = []
    for p in positions:
        row = {
            "ticker": p.ticker, "market": p.market, "entry_date": str(p.entry_date),
            "entry_price": p.entry_price, "quantity": p.quantity,
            "stop_loss": p.stop_loss, "take_profit": p.take_profit,
            "exit_mode": p.exit_mode,
        }
        if p.highest_close is not None:
            row["highest_close"] = p.highest_close
            row["current_trailing_sl"] = p.current_trailing_sl
        rows.append(row)
    path.write_text(
        "# Owner's open positions — managed via Telegram /add /remove or by hand.\n"
        "# highest_close/current_trailing_sl are pipeline-maintained (U7/G-1).\n"
        + yaml.safe_dump({"positions": rows}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def update_trailing_state(
    positions: list[Position], frames: dict[str, pd.DataFrame], atr_k: float = 3.0
) -> bool:
    """Persist each atr_trailing position's highest close + chandelier stop.

    Confirmed-scan only (preliminary scans must not feed in-progress bars).
    Returns True when any value changed (caller saves + workflow commits) —
    unchanged scans produce NO diff, keeping the commit history quiet.
    """
    changed = False
    for pos in positions:
        if pos.exit_mode != "atr_trailing":
            continue
        df = frames.get(pos.ticker)
        if df is None or df.empty:
            continue
        since = df[pd.to_datetime(df["date"]).dt.date >= pos.entry_date]
        if since.empty:
            continue
        highest = float(since["close"].max())
        if pos.highest_close is not None:
            highest = max(highest, pos.highest_close)  # never regress on restatement
        atr = since["atr14"].iloc[-1] if "atr14" in since.columns else float("nan")
        trailing = round(highest - atr_k * float(atr), 4) if atr == atr else pos.current_trailing_sl
        if highest != pos.highest_close or trailing != pos.current_trailing_sl:
            pos.highest_close = round(highest, 4)
            pos.current_trailing_sl = trailing
            changed = True
            logger.info(
                "trailing state %s: highest %.2f -> stop %s", pos.ticker, highest, trailing
            )
    return changed


def evaluate_position(pos: Position, df_ind: pd.DataFrame) -> tuple[str | None, dict]:
    """Check one position against the exit engine on the latest bar.

    Args:
        pos: Open position.
        df_ind: Indicator frame for the ticker (full history).

    Returns:
        (exit reason or None, summary dict for the holdings message).
    """
    df = df_ind[pd.to_datetime(df_ind["date"]).dt.date >= pos.entry_date]
    if df.empty:
        return None, {}
    last = df.iloc[-1]
    current = float(last["close"])
    highest = float(df["close"].max())
    if pos.highest_close is not None:  # persisted state survives data restatements
        highest = max(highest, pos.highest_close)
    state = exit_engine.PositionState(
        entry_price=pos.entry_price,
        current_close=current,
        highest_close_since_entry=highest,
        days_held=len(df) - 1,
        atr=None if pd.isna(last.get("atr14", np.nan)) else float(last["atr14"]),
        stop_loss=pos.stop_loss,
        take_profit=pos.take_profit,
    )
    try:
        reason = exit_engine.check_exit(pos.exit_mode, state)
    except ValueError:
        logger.exception("position %s: exit check failed", pos.ticker)
        reason = None
    pnl_pct = (current / pos.entry_price - 1) * 100
    to_stop = ((pos.stop_loss / current) - 1) * 100 if pos.stop_loss else float("nan")
    target_txt = (
        f"{((pos.take_profit / current) - 1) * 100:+.1f}%" if pos.take_profit else "추적/조건"
    )
    near_stop = bool(
        pos.stop_loss and current <= pos.stop_loss * (1 + settings.STOP_PROXIMITY_PCT / 100)
    )
    summary = {
        "ticker": pos.ticker,
        "name": pos.ticker,
        "market": pos.market,
        "entry_price": pos.entry_price,
        "current": current,
        "pnl_pct": pnl_pct,
        "to_stop_pct": to_stop,
        "to_target": target_txt,
        "near_stop": near_stop,
    }
    return reason, summary
