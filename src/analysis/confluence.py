"""⑦ Confluence (콘플루언스 메타전략): merge layer, not a signal generator.

When >= min_strategies base strategies fire BUY on the same ticker the same
day, emit ONE merged signal with summed strength x bonus multiplier, replacing
the individual signals for that ticker.
"""

import logging
from typing import Any

from src.analysis.base_strategy import Signal, load_strategy_config

logger = logging.getLogger(__name__)

CONFLUENCE_ID = "confluence"


def apply_confluence(signals: list[Signal], config: dict[str, Any] | None = None) -> list[Signal]:
    """Merge same-ticker multi-strategy signals into confluence signals.

    Args:
        signals: All base-strategy signals from one scan.
        config: strategies.yaml dict override (tests).

    Returns:
        Signals with merged tickers replaced by a single confluence Signal.
        If confluence is disabled in YAML, returns the input unchanged.
    """
    cfg = (config or load_strategy_config())["confluence"]
    if not cfg.get("enabled", False):
        return signals
    min_n = int(cfg["min_strategies"])
    bonus = float(cfg["bonus_multiplier"])

    by_ticker: dict[str, list[Signal]] = {}
    for sig in signals:
        by_ticker.setdefault(sig.ticker, []).append(sig)

    merged: list[Signal] = []
    for ticker, group in by_ticker.items():
        if len(group) < min_n:
            merged.extend(group)
            continue
        top = max(group, key=lambda s: s.strength)
        strategy_names = [s.strategy_id for s in group]
        indicators: dict[str, float] = {}
        for sig in group:
            indicators.update(sig.indicators)
        merged.append(
            Signal(
                ticker=ticker,
                name=top.name,
                market=top.market,
                strategy_id=CONFLUENCE_ID,
                direction="BUY",
                strength=round(min(100.0, sum(s.strength for s in group) * bonus), 1),
                price=top.price,
                signal_date=top.signal_date,
                indicators=indicators,
                suggested_stop_loss=top.suggested_stop_loss,
                suggested_take_profit=top.suggested_take_profit,
                exit_mode=top.exit_mode,
                reason=f"{len(group)}개 전략 동시 매수 신호 ({', '.join(strategy_names)}) — " + top.reason,
                tags=[t for s in group for t in s.tags],
            )
        )
        logger.info("confluence: %s merged %d signals", ticker, len(group))
    return merged
