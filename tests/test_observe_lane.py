"""Observe-lane tests: YAML flag, registry selection, scan reference split, message section."""

import copy
from datetime import date

import pandas as pd
import pytest

from config import settings
from src.analysis import registry
from src.analysis.base_strategy import BaseStrategy, Signal, load_strategy_config
from src.analysis.registry import get_strategies
from src.analysis.signal_engine import ScanResult, scan_market
from src.analysis.strategy_wyckoff import WyckoffSpringStrategy
from src.notify.messages import scan_message


def _config(**wyckoff_overrides) -> dict:
    """Real strategies.yaml copy with everything disabled; wyckoff overridable."""
    cfg = copy.deepcopy(load_strategy_config())
    for entry in cfg["strategies"].values():
        entry["enabled"] = False
        entry.pop("observe", None)
    cfg["strategies"]["wyckoff_spring"].update(wyckoff_overrides)
    return cfg


class TestObserveFlag:
    def test_default_false(self) -> None:
        s = WyckoffSpringStrategy(_config())
        assert s.observe is False

    def test_observe_true_when_disabled(self) -> None:
        s = WyckoffSpringStrategy(_config(observe=True))
        assert s.observe is True and s.enabled is False

    def test_enabled_wins_over_observe(self) -> None:
        s = WyckoffSpringStrategy(_config(observe=True, enabled=True))
        assert s.enabled is True and s.observe is False


class TestRegistrySelection:
    def test_observe_excluded_by_default(self) -> None:
        ids = [s.strategy_id for s in get_strategies(_config(observe=True))]
        assert "wyckoff_spring" not in ids

    def test_include_observe_adds_observe_strategies(self) -> None:
        ids = [s.strategy_id for s in get_strategies(_config(observe=True), include_observe=True)]
        assert ids == ["wyckoff_spring"]

    def test_enabled_only_false_unchanged(self) -> None:
        cfg = _config(observe=True)
        all_ids = [s.strategy_id for s in get_strategies(cfg, enabled_only=False)]
        assert set(cfg["strategies"]) <= set(all_ids) or len(all_ids) >= 6


# --- scan reference lane -----------------------------------------------


class _FireAlways(BaseStrategy):
    """Test-only strategy: unconditional BUY on the last bar."""

    name_kr = "더미"

    def evaluate(self, df: pd.DataFrame, ticker: str, name: str, market: str) -> Signal | None:
        last = df.iloc[-1]
        return Signal(
            ticker=ticker, name=name, market=market, strategy_id=self.strategy_id,
            direction="BUY", strength=50.0, price=float(last["close"]),
            signal_date=last["date"],
        )

    def conditions(self, df: pd.DataFrame) -> list[tuple[str, bool]]:
        return [("항상 충족", True)]


class _DummyEnabled(_FireAlways):
    strategy_id = "dummy_enabled"


class _DummyObserve(_FireAlways):
    strategy_id = "dummy_observe"


@pytest.fixture
def dummy_registry():
    registry._import_strategy_modules()
    registry._REGISTRY["dummy_enabled"] = _DummyEnabled
    registry._REGISTRY["dummy_observe"] = _DummyObserve
    yield
    registry._REGISTRY.pop("dummy_enabled", None)
    registry._REGISTRY.pop("dummy_observe", None)


def _scan_config() -> dict:
    cfg = _config()
    cfg["strategies"]["dummy_enabled"] = {"enabled": True, "min_bars": 10, "params": {}}
    cfg["strategies"]["dummy_observe"] = {
        "enabled": False, "observe": True, "min_bars": 10, "params": {},
    }
    return cfg


def _ohlcv(tickers: list[str], bars: int = 80) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2026-01-05", periods=bars)
    for t in tickers:
        for i, d in enumerate(dates):
            price = 100.0 + i * 0.1
            rows.append({
                "ticker": t, "date": d.date(), "open": price, "high": price * 1.01,
                "low": price * 0.99, "close": price, "volume": 5_000_000,
            })
    return pd.DataFrame(rows)


class TestScanReferenceLane:
    def test_observe_signals_split_into_references(self, dummy_registry, monkeypatch) -> None:
        monkeypatch.setattr(settings, "RS_PERCENTILE_FLOOR", 0.0)
        result = scan_market(
            "us", _ohlcv(["AAA", "BBB"]), config=_scan_config(),
            check_earnings=False, fetch_regime=False,
        )
        assert {s.strategy_id for s in result.signals} == {"dummy_enabled"}
        assert {s.strategy_id for s in result.references} == {"dummy_observe"}
        assert all(s.is_reference for s in result.references)
        assert all(not s.is_reference for s in result.signals)
        assert all(any("추천 아님" in t for t in s.tags) for s in result.references)
        # frames must exist for reference tickers too (reports are built from them)
        assert all(s.ticker in result.signal_frames for s in result.references)

    def test_reference_cap_and_top_n_untouched(self, dummy_registry, monkeypatch) -> None:
        monkeypatch.setattr(settings, "RS_PERCENTILE_FLOOR", 0.0)
        tickers = ["T1", "T2", "T3", "T4", "T5"]
        result = scan_market(
            "us", _ohlcv(tickers), config=_scan_config(),
            check_earnings=False, fetch_regime=False,
        )
        assert len(result.references) == settings.OBSERVE_MAX_ITEMS
        assert len(result.signals) == len(tickers)  # cap never eats recommendations


# --- Telegram message section -------------------------------------------


def _ref_signal(ticker: str = "SPRG") -> Signal:
    return Signal(
        ticker=ticker, name="스프링주", market="us", strategy_id="wyckoff_spring",
        direction="BUY", strength=40.0, price=12.34, signal_date=date(2026, 7, 17),
        is_reference=True, tags=["🔍 관찰 — 검증 미통과 · 추천 아님"],
    )


class TestScanMessageReferences:
    def test_reference_section_rendered(self) -> None:
        result = ScanResult(
            market="us", scan_date=date(2026, 7, 17), signals=[], total_scanned=100,
            references=[_ref_signal()],
        )
        text = scan_message(result, {"SPRG": "https://x/reports/sprg.html"})
        assert "추천 아님" in text
        assert "SPRG" in text
        assert "https://x/reports/sprg.html" in text
        assert "시그널 0개" in text  # references never count as signals

    def test_no_references_no_section(self) -> None:
        result = ScanResult(
            market="us", scan_date=date(2026, 7, 17), signals=[], total_scanned=100,
        )
        text = scan_message(result, {})
        assert "관찰" not in text
