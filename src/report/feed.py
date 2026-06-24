"""PWA feed (``data/app/feed.json``) — the single JSON the iPhone PWA consumes.

Emitted on every scan and the weekly job. Rides the orphan ``data`` branch
automatically: ``store.publish_to_data_branch`` globs ``data/**/*.json``, so
writing ``data/app/feed.json`` is enough (no publisher/store changes). The PWA
fetches it over ``raw.githubusercontent.com``.

NEUTRAL by construction: it carries recommendation signals + the VIRTUAL paper
portfolio + adaptive system state, and NEVER owner positions / entry prices /
quantities / P&L (§2 rule #4). A regression test greps the output for leaks.

The signal list is ACCUMULATED across scans: each call merges the current
scan's cards into the previously published feed (deduped on
``(signal_date, ticker, strategy_id)``) and prunes anything older than
``settings.FEED_RETENTION_DAYS`` — one market's scan never wipes the other's.
"""

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import settings
from src.analysis.base_strategy import Signal

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# Paper open/closed fields exposed to the PWA (virtual, public — no owner data).
_OPEN_FIELDS = (
    "ticker", "market", "strategy_id", "grade", "entry_date",
    "entry_price", "entry_fill", "stop_loss", "take_profit", "exit_mode",
    "current_price", "unrealized_pct", "days_held",
)
_CLOSED_FIELDS = (
    "ticker", "market", "grade", "strategy_id", "entry_date", "exit_date",
    "return_pct", "holding_days", "exit_reason",
)


def _num(x: Any, ndigits: int = 2) -> float | None:
    """Round to a finite float, or None for NaN/inf/None/non-numeric."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, ndigits)


def _clean(obj: Any) -> Any:
    """Recursively JSON-safe a structure: NaN/inf -> None, dates -> ISO str."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


def _strategy_names() -> dict[str, str]:
    """strategy_id -> Korean display name (best-effort)."""
    try:
        from src.analysis.registry import get_strategies

        return {s.strategy_id: s.name_kr for s in get_strategies(enabled_only=False)}
    except Exception:
        logger.debug("feed: strategy name lookup failed", exc_info=True)
        return {}


def _yahoo_symbol(sig: Signal, exchange: str | None) -> str:
    """Exact Yahoo symbol. KR needs .KS (KOSPI) / .KQ (KOSDAQ); US is the bare
    ticker. When the KR exchange is unknown, return the bare code so the quote
    proxy falls back to its .KS→.KQ probe."""
    if sig.market != "kr":
        return sig.ticker
    if exchange == "KOSDAQ":
        return f"{sig.ticker}.KQ"
    if exchange == "KOSPI":
        return f"{sig.ticker}.KS"
    return sig.ticker


def _signal_card(sig: Signal, url: str | None, names: dict[str, str], exchange: str | None) -> dict:
    """Serialize one Signal into a neutral watchlist card."""
    sd = sig.signal_date.isoformat() if isinstance(sig.signal_date, date) else sig.signal_date
    return {
        "signal_date": sd,
        "ticker": sig.ticker,
        "yahoo_symbol": _yahoo_symbol(sig, exchange),
        "name": sig.name,
        "market": sig.market,
        "strategy_id": sig.strategy_id,
        "strategy_name": names.get(sig.strategy_id, sig.strategy_id),
        "strength": _num(sig.strength, 1),
        "grade": sig.grade,
        "grade_value": _num(sig.grade_value, 1),
        "confidence": _num(sig.confidence, 3),
        "regime_factor": _num(sig.regime_factor, 3),
        "price": _num(sig.price),
        "entry_zone_top": _num(sig.entry_zone_top),
        "stop_loss": _num(sig.suggested_stop_loss),
        "take_profit": _num(sig.suggested_take_profit),
        "exit_mode": sig.exit_mode,
        "wyckoff_badge": sig.wyckoff_badge,
        "reason": sig.reason,
        "tags": list(sig.tags or []),
        "contrarian": list(sig.contrarian or []),
        "report_url": url,
    }


def _merge_signals(existing: list[dict], new_cards: list[dict]) -> list[dict]:
    """Dedupe-merge (new wins) on (signal_date, ticker, strategy_id), prune, cap."""
    def key(c: dict) -> tuple:
        return (c.get("signal_date"), c.get("ticker"), c.get("strategy_id"))

    merged: dict[tuple, dict] = {key(c): c for c in existing if isinstance(c, dict)}
    for c in new_cards:
        merged[key(c)] = c

    cutoff = (date.today() - timedelta(days=settings.FEED_RETENTION_DAYS)).isoformat()
    cards = [c for c in merged.values() if (c.get("signal_date") or "") >= cutoff]
    cards.sort(
        key=lambda c: (c.get("signal_date") or "", c.get("strength") or 0.0),
        reverse=True,
    )
    return cards[: settings.FEED_MAX_SIGNALS]


def _paper_block() -> dict:
    """Virtual paper-portfolio snapshot (recomputed; not a source of truth)."""
    try:
        from src.paper import portfolio as paper
        from src.paper import stats as paper_stats

        trades = paper.load_trades()
        open_rows = paper.load_open()
        summary = paper_stats.summarize(trades, open_rows)
        curve = paper_stats.equity_curve(trades)

        recent_closed: list[dict] = []
        if trades is not None and not trades.empty:
            import pandas as pd

            t = trades.copy()
            t["_ed"] = pd.to_datetime(t["exit_date"], errors="coerce")
            t = t.sort_values("_ed", ascending=False).head(20)
            for _, row in t.iterrows():
                recent_closed.append({f: row.get(f) for f in _CLOSED_FIELDS if f in t.columns})

        return _clean({
            "summary": summary,
            "equity_curve": curve.to_dict("records") if not curve.empty else [],
            "by_grade": paper_stats.breakdown(trades, "grade") if (trades is not None and not trades.empty) else [],
            "open": [{f: r.get(f) for f in _OPEN_FIELDS if f in r} for r in open_rows],
            "recent_closed": recent_closed,
        })
    except Exception:
        logger.exception("feed: paper block failed")
        return {}


def _system_block() -> dict:
    """Adaptive/system state for the System view."""
    out: dict = {
        "adaptive_loop_enabled": bool(settings.ADAPTIVE_LOOP_ENABLED),
        "min_strength_send": _num(settings.MIN_STRENGTH_SEND, 1),
    }
    try:
        from src.analysis.registry import get_strategies

        out["enabled_strategies"] = [
            {"strategy_id": s.strategy_id, "name": s.name_kr}
            for s in get_strategies(enabled_only=False) if getattr(s, "enabled", False)
        ]
    except Exception:
        logger.debug("feed: enabled strategies lookup failed", exc_info=True)
    try:
        from src.adaptive.cutoff import effective_cutoff

        out["effective_cutoff"] = _num(effective_cutoff(), 1)
    except Exception:
        logger.debug("feed: effective_cutoff failed", exc_info=True)
    try:
        from src.adaptive.audit import AUDIT_FILE

        if AUDIT_FILE.exists():
            audit = json.loads(AUDIT_FILE.read_text())
            if isinstance(audit, list):
                out["recent_audit"] = _clean(audit[-10:])
    except Exception:
        logger.debug("feed: audit read failed", exc_info=True)
    return out


def build_feed(
    signals: list[Signal] | None = None,
    urls: dict[str, str] | None = None,
    kr_markets: dict[str, str] | None = None,
    path: Path | None = None,
) -> Path:
    """Build/merge ``feed.json`` and write it under the data root.

    Args:
        signals: Current scan's (alerted) signals; None on the weekly refresh.
        urls: ticker -> report URL map (from ``_scan``).
        kr_markets: ticker -> "KOSPI"|"KOSDAQ" (KR scans) for exact Yahoo symbols.
        path: Override output path (tests).

    Returns:
        The path written.
    """
    out_path = path or settings.FEED_FILE
    urls = urls or {}
    kr_markets = kr_markets or {}

    existing: list[dict] = []
    if out_path.exists():
        try:
            prior = json.loads(out_path.read_text())
            existing = prior.get("signals", []) if isinstance(prior, dict) else []
        except Exception:
            logger.warning("feed: could not read prior %s; starting fresh", out_path)

    names = _strategy_names()
    new_cards = [
        _signal_card(s, urls.get(s.ticker), names, kr_markets.get(s.ticker)) for s in (signals or [])
    ]
    cards = _merge_signals(existing, new_cards)

    feed = {
        "schema_version": settings.FEED_SCHEMA_VERSION,
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "signals": cards,
        "paper": _paper_block(),
        "system": _system_block(),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2))
    logger.info("feed: wrote %d signals to %s", len(cards), out_path)
    return out_path
