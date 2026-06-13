"""Closed-trade ledger — realized P/L + trading-discipline tracking.

Every position exit (recorded on /remove) is persisted so the weekly job can
measure REALIZED performance and the gap between what the system recommended
and what the owner actually did. This is the foundation for fighting
emotion-driven trading: you cannot improve discipline you do not measure.

Stored as Parquet under DATA_ROOT/trades/ — it rides the orphan `data` branch
exactly like signals.parquet (the position-remove path restores then publishes
the data branch, so the file persists across fresh runner checkouts).

HONESTY: when /remove supplies no fill price, the exit price falls back to the
latest available close (exit_price_source="estimated_close"). It is always
flagged and never presented as the owner's actual fill.
"""

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

CLOSED_TRADES_FILE = settings.DATA_ROOT / "trades" / "closed_trades.parquet"

COLUMNS = [
    "ticker", "market", "entry_date", "entry_price", "quantity",
    "stop_loss", "take_profit", "exit_mode", "exit_date", "exit_price",
    "exit_price_source", "return_pct", "holding_days", "exit_reason",
]


def record_closed_trade(record: dict, path: Path | None = None) -> int:
    """Append one closed-trade record to the ledger.

    Args:
        record: Mapping with the COLUMNS keys (missing keys stored as None).
        path: Override path (tests).

    Returns:
        Total number of trades now stored.
    """
    path = path or CLOSED_TRADES_FILE
    row = pd.DataFrame([{c: record.get(c) for c in COLUMNS}], columns=COLUMNS)
    if path.exists():
        row = pd.concat([pd.read_parquet(path), row], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    row.to_parquet(path, compression="zstd", index=False)
    logger.info("ledger: %s exit recorded (%d trades total)", record.get("ticker"), len(row))
    return len(row)


def load_closed_trades(path: Path | None = None) -> pd.DataFrame:
    """Load the closed-trade ledger (empty frame when none)."""
    path = path or CLOSED_TRADES_FILE
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_parquet(path)


def discipline_summary_kr(trades: pd.DataFrame) -> str:
    """Korean realized-performance summary from the closed-trade ledger.

    Reports win rate, average win/loss, profit factor and average holding —
    the owner's ACTUAL results, distinct from the strategies' paper stats.
    """
    if trades.empty:
        return "🧾 실현 성과: 아직 기록된 청산이 없습니다 (/remove 시 자동 기록됩니다)."
    r = pd.to_numeric(trades["return_pct"], errors="coerce").dropna()
    n = len(r)
    if n == 0:
        return "🧾 실현 성과: 청산 기록은 있으나 수익률 계산 불가."
    wins = int((r > 0).sum())
    losses = n - wins
    gross_win = float(r[r > 0].sum())
    gross_loss = float(-r[r <= 0].sum())
    avg_hold = pd.to_numeric(trades["holding_days"], errors="coerce").dropna().mean()
    lines = [
        f"🧾 실현 성과 (청산 {n}건)",
        f"· 승률 {wins / n * 100:.0f}% ({wins}승 {losses}패) · 평균 보유 {avg_hold:.0f}일",
    ]
    if wins and losses:
        lines.append(
            f"· 평균 수익 {r[r > 0].mean():+.1f}% / 평균 손실 {r[r <= 0].mean():+.1f}%"
        )
    else:
        lines.append(f"· 평균 수익률 {r.mean():+.1f}%")
    if gross_loss > 0:
        lines.append(f"· Profit Factor {gross_win / gross_loss:.2f}")
    elif wins:
        lines.append("· Profit Factor ∞ (손실 청산 없음)")
    est = int((trades["exit_price_source"] == "estimated_close").sum())
    if est:
        lines.append(
            f"· ⚠️ {est}건은 청산가 추정(최근 종가) — 실제 체결가로 /remove 하면 정확도↑"
        )
    return "\n".join(lines)
