"""Strategy plugin contract: Signal dataclass + BaseStrategy ABC.

Each strategy reads its parameters from config/strategies.yaml (single source
of truth, shared with the Phase-4 backtesting.py adapters) and evaluates the
LAST bar of a per-ticker indicator frame, emitting Signal | None.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from config import settings

logger = logging.getLogger(__name__)

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
    # --- U4 scan-time enrichments (filled in main._scan, None until then) ---
    grade: str | None = None  # A | B | C
    grade_value: float | None = None  # composite 0-100 (Grade.value; signals.parquet)
    grade_basis: str = ""  # derivation string (report)
    confidence: float | None = None  # per-ticker confidence 0-1 (signals.parquet)
    regime_factor: float | None = None  # regime downgrade_factor (signals.parquet)
    wyckoff_badge: str = ""  # 🟢 매집권 / 🟡 관찰 / ⚪ 해당 없음
    entry_zone_top: float | None = None  # 매수 범위 상단 (above = 추격 금지)
    contrarian: list[str] = field(default_factory=list)  # against-the-buy list
    is_reference: bool = False  # observe-lane signal: never a recommendation


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
        # Observe lane: run in scans as reference-only (never a recommendation).
        # enabled wins — a Phase-4-passed strategy needs no observation.
        self.observe: bool = bool(cfg.get("observe", False)) and not self.enabled
        if cfg.get("observe") and self.enabled:
            logger.warning("%s: observe ignored — strategy is enabled", self.strategy_id)
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

    @abstractmethod
    def conditions(self, df: pd.DataFrame) -> list[tuple[str, bool]]:
        """Labeled entry conditions on the LAST bar (single source of truth).

        evaluate() consumes this; /analyze renders it as a Korean checklist
        ("6개 조건 중 4개 충족" style). NaN inputs make a condition False.

        Args:
            df: compute_indicators() frame, ascending date order.

        Returns:
            [(condition label in Korean, satisfied?), ...] in display order.
        """

    def checklist_kr(self, df: pd.DataFrame) -> str:
        """One-line Korean checklist summary for /analyze."""
        checks = self.conditions(df)
        met = sum(1 for _, ok in checks if ok)
        failed = [label for label, ok in checks if not ok]
        head = f"{self.name_kr}: {len(checks)}개 조건 중 {met}개 충족"
        if failed:
            head += f" — 미충족: {', '.join(failed)}"
        return head

    def should_exit(self, df: pd.DataFrame) -> str | None:
        """Strategy-specific sell condition on the LAST bar (None = hold).

        Engine-level exits (stop/target/trailing/ROI/time) are evaluated
        separately by src.risk.exit_engine; this only adds the strategy's own
        indicator-based exit (e.g. RSI > 70). Default: no extra condition.

        Args:
            df: compute_indicators() frame up to and including the current bar.

        Returns:
            Korean exit reason, or None.
        """
        return None

    def _snapshot(self, row: pd.Series, keys: list[str]) -> dict[str, float]:
        """Collect a JSON-safe indicator snapshot for the Signal."""
        snap: dict[str, float] = {}
        for key in keys:
            value = row.get(key)
            if pd.notna(value):
                snap[key] = round(float(value), 4)
        return snap
