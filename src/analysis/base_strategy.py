"""Strategy plugin contract: Signal dataclass + BaseStrategy ABC.

Each strategy reads its parameters from config/strategies.yaml (single source
of truth, shared with the Phase-4 backtesting.py adapters) and evaluates the
LAST bar of a per-ticker indicator frame, emitting Signal | None.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from config import settings

STRATEGIES_YAML = settings.REPO_ROOT / "config" / "strategies.yaml"


@lru_cache(maxsize=1)
def load_strategy_config(path: str | None = None) -> dict[str, Any]:
    """Load and cache config/strategies.yaml."""
    with open(path or STRATEGIES_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class Signal:
    """A single BUY recommendation emitted by a strategy."""

    ticker: str
    name: str  # human-readable security name
    market: str  # "us" | "kr"
    strategy_id: str
    direction: str  # always "BUY" (long-only system)
    strength: float  # 0-100
    price: float  # reference close
    signal_date: date
    indicators: dict[str, float] = field(default_factory=dict)  # snapshot
    suggested_stop_loss: float | None = None
    suggested_take_profit: float | None = None
    exit_mode: str = "fixed"  # fixed | atr_trailing | roi_table
    reason: str = ""  # Korean, for Telegram/report
    tags: list[str] = field(default_factory=list)  # e.g. 실적발표 경고, 시장 약세


class BaseStrategy(ABC):
    """Contract every strategy plugin implements.

    Class attributes (set by subclasses):
        strategy_id: YAML key under `strategies:`.
        name_kr: Korean display name.
    """

    strategy_id: str = ""
    name_kr: str = ""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Bind YAML parameters.

        Args:
            config: Full strategies.yaml dict (injected in tests); loaded if None.
        """
        cfg = (config or load_strategy_config())["strategies"][self.strategy_id]
        self.params: dict[str, Any] = cfg["params"]
        self.enabled: bool = bool(cfg.get("enabled", False))
        self.exit_mode: str = cfg.get("exit_mode", "fixed")
        self.min_bars: int = int(cfg.get("min_bars", 150))

    def eligible(self, df: pd.DataFrame) -> bool:
        """History check: enough bars for this strategy's indicators."""
        return len(df) >= self.min_bars

    @abstractmethod
    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        """Evaluate the LAST bar of an indicator frame.

        Args:
            df: compute_indicators() output, ascending date order.
            ticker: Ticker code.
            name: Security display name.
            market: "us" | "kr".

        Returns:
            Signal if entry conditions are all met on the last bar, else None.
        """

    def _snapshot(self, row: pd.Series, keys: list[str]) -> dict[str, float]:
        """Collect a JSON-safe indicator snapshot for the Signal."""
        snap: dict[str, float] = {}
        for key in keys:
            value = row.get(key)
            if pd.notna(value):
                snap[key] = round(float(value), 4)
        return snap
