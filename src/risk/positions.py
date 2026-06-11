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
            )
        )
    return out


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
    state = exit_engine.PositionState(
        entry_price=pos.entry_price,
        current_close=current,
        highest_close_since_entry=float(df["close"].max()),
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
    summary = {
        "ticker": pos.ticker,
        "name": pos.ticker,
        "current": current,
        "pnl_pct": pnl_pct,
        "to_stop_pct": to_stop,
        "to_target": target_txt,
    }
    return reason, summary
