"""Phase-4 validation runner: every registered strategy through every gate.

Gating sample: US (primary market per spec) — KR sample stats are reported
alongside for visibility but do not decide `enabled`. Sequential processing
throughout (8GB rule). Costs always on.

Invoked via: python main.py backtest [--smoke]
"""

import logging
import os
from datetime import date, timedelta

os.environ.setdefault("TQDM_DISABLE", "1")  # silence backtesting.py progress bars

import pandas as pd

from config import settings
from src.analysis.base_strategy import load_strategy_config
from src.analysis.indicators import compute_indicators
from src.analysis.registry import get_strategies
from src.backtest.validation import GateReport, format_report, validate_strategy
from src.data.store import ParquetStore

logger = logging.getLogger(__name__)


def fetch_index_series(market: str, years: int) -> pd.Series:
    """Fetch the benchmark index close series (S&P500 / KOSPI)."""
    start = date.today() - timedelta(days=365 * years + 30)
    if market == "kr":
        import FinanceDataReader as fdr

        return fdr.DataReader("KS11", start)["Close"].dropna()
    import yfinance as yf

    df = yf.download("^GSPC", start=start, auto_adjust=True, threads=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].dropna()


def build_frames(market: str, n_sample: int, min_bars: int = 260) -> dict[str, pd.DataFrame]:
    """Load stored OHLCV for an evenly-spaced universe sample; compute indicators.

    Tickers with fewer than min_bars bars are excluded (NaN guard).
    """
    store = ParquetStore()
    data = store.load(market)
    if data.empty:
        return {}
    data["date"] = pd.to_datetime(data["date"]).dt.date
    tickers = sorted(data["ticker"].unique())
    step = max(1, len(tickers) // n_sample)
    sample = tickers[::step][:n_sample]
    frames: dict[str, pd.DataFrame] = {}
    for t in sample:  # sequential (8GB rule)
        df = data[data["ticker"] == t].sort_values("date").reset_index(drop=True)
        if len(df) < min_bars:
            continue
        frames[t] = compute_indicators(df)
    logger.info("frames[%s]: %d/%d sample tickers usable", market, len(frames), len(sample))
    return frames


def filter_strategies(strategies: list, only: str | None) -> list:
    """Keep only the requested strategy_id (None = all).

    Args:
        strategies: get_strategies() output.
        only: strategy_id to isolate, or None.

    Returns:
        Filtered list.

    Raises:
        ValueError: only does not match any registered strategy.
    """
    if only is None:
        return list(strategies)
    kept = [s for s in strategies if s.strategy_id == only]
    if not kept:
        raise ValueError(f"unknown strategy id: {only!r}")
    return kept


def run(smoke: bool = False, only: str | None = None) -> dict[str, GateReport]:
    """Run the full validation suite; returns {strategy_id: GateReport}.

    Args:
        smoke: Tiny sample / fewer MC runs — debug only, never gates YAML.
        only: Validate a single strategy_id (None = all registered).
    """
    config = load_strategy_config()
    strategies = filter_strategies(get_strategies(config, enabled_only=False), only)
    n_us = 8 if smoke else settings.VAL_SAMPLE_US
    n_kr = 4 if smoke else settings.VAL_SAMPLE_KR

    us_frames = build_frames("us", n_us)
    kr_frames = build_frames("kr", n_kr)
    us_index = fetch_index_series("us", settings.HISTORY_YEARS)
    kr_index = fetch_index_series("kr", settings.HISTORY_YEARS)

    reports: dict[str, GateReport] = {}
    print("\n" + "=" * 78)
    print(f"VALIDATION RUN — US sample {len(us_frames)} (GATING) / KR sample {len(kr_frames)} (보고용)")
    print("주의: 백테스트는 현재 유니버스 기준 — 상장폐지 종목 제외로 생존 편향(낙관적 왜곡) 존재")
    print("=" * 78)
    for strategy in strategies:
        cls = type(strategy)
        report = validate_strategy(cls, config, us_frames, {t: "us" for t in us_frames}, us_index)
        reports[strategy.strategy_id] = report
        print("\n" + format_report(report))
        if kr_frames:
            kr_report = validate_strategy(cls, config, kr_frames, {t: "kr" for t in kr_frames}, kr_index)
            print(
                f"  [KR 참고] IS n={kr_report.is_stats['n']} PF={kr_report.is_stats['profit_factor']:.2f} / "
                f"OoS n={kr_report.oos_stats['n']} PF={kr_report.oos_stats['profit_factor']:.2f}"
                if kr_report.is_stats["n"] and kr_report.oos_stats["n"]
                else "  [KR 참고] 표본 내 거래 없음"
            )

    return reports
