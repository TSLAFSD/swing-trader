"""Paper-portfolio analytics (P-B) — pure, derived from the P-A stores.

Everything here is recomputed from paper/trades.parquet (closed) + the open
positions list; nothing is persisted as a source of truth. Units match
risk/trade_ledger.py: return_pct / mae_pct / mfe_pct are PERCENT, holding_days
is CALENDAR days, pnl is in abstract notional units (PAPER_START_EQUITY base).

Capital model: each trade is a fixed notional (START * TRADE_FRACTION); the
equity curve is START + cumulative realized pnl, plus open mark-to-market for
the current value. US and KR share one return-space pool (no FX).
"""

import math

import pandas as pd

from config import settings


def equity_curve(trades: pd.DataFrame, start_equity: float | None = None) -> pd.DataFrame:
    """Realized equity over time from closed trades (sorted by exit date).

    Returns:
        Frame [date(str), equity, drawdown_pct]; empty when no closed trades.
    """
    start = settings.PAPER_START_EQUITY if start_equity is None else start_equity
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["date", "equity", "drawdown_pct"])
    df = trades.copy()
    df["exit_date"] = pd.to_datetime(df["exit_date"], errors="coerce")
    df = df.dropna(subset=["exit_date"]).sort_values("exit_date")
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    equity = start + pnl.cumsum()
    peak = equity.cummax()
    drawdown = (equity / peak - 1.0) * 100.0
    return pd.DataFrame(
        {
            "date": df["exit_date"].dt.date.astype(str).to_numpy(),
            "equity": equity.round(2).to_numpy(),
            "drawdown_pct": drawdown.round(2).to_numpy(),
        }
    )


def _open_unrealized_pnl(open_rows: list[dict]) -> float:
    """Mark-to-market pnl of open virtual positions (abstract notional units)."""
    total = 0.0
    for row in open_rows or []:
        cash = float(row.get("cash_allocated") or 0.0)
        unreal_pct = float(row.get("unrealized_pct") or 0.0)
        total += cash * unreal_pct / 100.0
    return total


def summarize(
    trades: pd.DataFrame, open_rows: list[dict] | None = None, start_equity: float | None = None
) -> dict:
    """Headline paper-portfolio metrics from closed trades + open positions."""
    start = settings.PAPER_START_EQUITY if start_equity is None else start_equity
    open_rows = open_rows or []
    out: dict = {
        "start_equity": start,
        "n_closed": 0,
        "win_rate": float("nan"),
        "profit_factor": float("nan"),
        "avg_holding": float("nan"),
        "realized_pnl": 0.0,
        "max_drawdown_pct": 0.0,
        "best": None,
        "worst": None,
        "n_open": len(open_rows),
        "open_unrealized_pnl": _open_unrealized_pnl(open_rows),
        "period_start": None,
        "period_end": None,
    }
    dates: list[pd.Timestamp] = []
    if trades is not None and not trades.empty:
        n = len(trades)
        out["n_closed"] = n
        ret = pd.to_numeric(trades["return_pct"], errors="coerce")
        valid = ret.dropna()
        if len(valid):
            wins = float((valid > 0).sum())
            out["win_rate"] = wins / len(valid)
            gross_win = float(valid[valid > 0].sum())
            gross_loss = float(-valid[valid <= 0].sum())
            if gross_loss > 0:
                out["profit_factor"] = gross_win / gross_loss
            elif wins:
                out["profit_factor"] = float("inf")
            best_i, worst_i = ret.idxmax(), ret.idxmin()
            out["best"] = {"ticker": trades.loc[best_i, "ticker"], "return_pct": float(ret.loc[best_i])}
            out["worst"] = {"ticker": trades.loc[worst_i, "ticker"], "return_pct": float(ret.loc[worst_i])}
        out["avg_holding"] = float(pd.to_numeric(trades["holding_days"], errors="coerce").dropna().mean())
        out["realized_pnl"] = float(pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0).sum())
        curve = equity_curve(trades, start)
        if not curve.empty:
            out["max_drawdown_pct"] = float(curve["drawdown_pct"].min())
        dates += pd.to_datetime(trades["entry_date"], errors="coerce").dropna().tolist()
        dates += pd.to_datetime(trades["exit_date"], errors="coerce").dropna().tolist()
    for row in open_rows:
        dates.append(pd.to_datetime(row.get("entry_date"), errors="coerce"))
        dates.append(pd.to_datetime(row.get("last_mark_date") or row.get("entry_date"), errors="coerce"))
    dates = [d for d in dates if pd.notna(d)]
    if dates:
        out["period_start"] = min(dates).date()
        out["period_end"] = max(dates).date()
    out["current_equity"] = start + out["realized_pnl"] + out["open_unrealized_pnl"]
    out["realized_return_pct"] = out["realized_pnl"] / start * 100.0 if start else 0.0
    out["total_return_pct"] = (out["current_equity"] / start - 1.0) * 100.0 if start else 0.0
    return out


def breakdown(trades: pd.DataFrame, key: str) -> list[dict]:
    """Per-group (e.g. grade, strategy_id, exit_reason) hit-rate breakdown."""
    if trades is None or trades.empty or key not in trades.columns:
        return []
    rows = []
    for value, grp in trades.groupby(key):
        ret = pd.to_numeric(grp["return_pct"], errors="coerce").dropna()
        rows.append(
            {
                "key": str(value),
                "n": len(grp),
                "win_rate": float((ret > 0).mean()) if len(ret) else float("nan"),
                "avg_return": float(ret.mean()) if len(ret) else float("nan"),
            }
        )
    return sorted(rows, key=lambda r: r["n"], reverse=True)


def _pf_str(pf: float) -> str:
    if pf != pf:  # nan
        return "—"
    return "∞" if math.isinf(pf) else f"{pf:.2f}"


def summary_kr(
    trades: pd.DataFrame,
    open_rows: list[dict] | None = None,
    *,
    benchmark_pct: float | None = None,
    url: str | None = None,
    start_equity: float | None = None,
) -> str:
    """Korean Telegram summary of the virtual portfolio's performance."""
    s = summarize(trades, open_rows, start_equity)
    start = s["start_equity"]
    if s["n_closed"] == 0 and s["n_open"] == 0:
        return "🤖 가상 포트폴리오: 아직 거래가 없습니다 (다음 확정 스캔에서 A등급 시그널을 가상 매수합니다)."
    lines = ["🤖 가상 포트폴리오 성과 (AI 페이퍼 트레이딩)"]
    lines.append(f"· 총수익률 {s['total_return_pct']:+.1f}% · 현재 자산 {s['current_equity']:,.0f} (시작 {start:,.0f})")
    if s["n_closed"]:
        wr = f"{s['win_rate'] * 100:.0f}%" if s["win_rate"] == s["win_rate"] else "—"
        lines.append(
            f"· 청산 {s['n_closed']}건 · 승률 {wr} · PF {_pf_str(s['profit_factor'])} · 평균보유 {s['avg_holding']:.0f}일"
        )
        lines.append(f"· 최대낙폭(MDD) {s['max_drawdown_pct']:.1f}%")
        if s["best"] and s["worst"]:
            lines.append(
                f"· 최고 {s['best']['ticker']} {s['best']['return_pct']:+.1f}% / "
                f"최저 {s['worst']['ticker']} {s['worst']['return_pct']:+.1f}%"
            )
    if s["n_open"]:
        lines.append(f"· 보유 {s['n_open']}개 (평가손익 {s['open_unrealized_pnl']:+,.0f})")
    if benchmark_pct is not None:
        excess = s["total_return_pct"] - benchmark_pct
        lines.append(f"· S&P500 동기간 {benchmark_pct:+.1f}% → 초과수익 {excess:+.1f}%p")
    if url:
        lines.append(f"📄 {url}")
    return "\n".join(lines)
