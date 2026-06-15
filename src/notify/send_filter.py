"""Send-stage cutoffs (U1/A-2) — separate from ranking.

Reports are still generated for filtered signals (weekly tracking needs
them); only the Telegram message is gated. The health-check line reports the
excluded count — silence must never hide filtering.
"""

import logging
from dataclasses import dataclass

from config import settings
from src.analysis.base_strategy import Signal
from src.backtest.confidence import ConfidenceReport

logger = logging.getLogger(__name__)


@dataclass
class SendDecision:
    """One signal's send verdict with Korean reasons for the log."""

    signal: Signal
    send: bool
    reasons: list[str]


def stop_width_pct(sig: Signal) -> float | None:
    """Suggested stop distance from entry in percent (None when no stop)."""
    if sig.suggested_stop_loss is None or sig.price <= 0:
        return None
    return abs(sig.price - sig.suggested_stop_loss) / sig.price * 100.0


def filter_for_send(
    signals: list[Signal], confs: dict[str, ConfidenceReport]
) -> tuple[list[Signal], list[SendDecision]]:
    """Apply send cutoffs; returns (sendable signals, excluded decisions).

    Cutoffs (config/settings.py):
      - confidence PF >= MIN_PROFIT_FACTOR_SEND (NaN/inf-safe: inf passes)
      - confidence n_trades >= MIN_SAMPLE_SEND
      - final strength >= MIN_STRENGTH_SEND
      - stop width <= MAX_STOP_LOSS_PCT (STOP_TOO_WIDE_MODE: drop | tag)
    """
    from src.adaptive.cutoff import effective_cutoff

    cutoff = effective_cutoff()  # adaptive (Lever 3) or MIN_STRENGTH_SEND when off
    sendable: list[Signal] = []
    excluded: list[SendDecision] = []
    for sig in signals:
        reasons: list[str] = []
        conf = confs.get(sig.ticker)
        if conf is not None:
            if conf.n_trades < settings.MIN_SAMPLE_SEND:
                reasons.append(f"표본 {conf.n_trades}건 < {settings.MIN_SAMPLE_SEND}")
            pf = conf.profit_factor
            if pf == pf and pf < settings.MIN_PROFIT_FACTOR_SEND:  # NaN-safe
                reasons.append(f"PF {pf:.2f} < {settings.MIN_PROFIT_FACTOR_SEND}")
        if sig.strength < cutoff:
            reasons.append(f"강도 {sig.strength:.0f} < {cutoff:.0f}")
        width = stop_width_pct(sig)
        if width is not None and width > settings.MAX_STOP_LOSS_PCT:
            if settings.STOP_TOO_WIDE_MODE == "tag":
                sig.tags.append(f"⚠️ 손절폭 과대(-{width:.0f}%) — 변동성 위험")
            else:
                reasons.append(f"손절폭 -{width:.0f}% > {settings.MAX_STOP_LOSS_PCT:.0f}%")
        if reasons:
            excluded.append(SendDecision(signal=sig, send=False, reasons=reasons))
            logger.info("send filter: %s excluded (%s)", sig.ticker, "; ".join(reasons))
        else:
            sendable.append(sig)
    return sendable, excluded
