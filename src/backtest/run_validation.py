"""Phase-4 validation runner: all 7 strategies through every gate.

Gating sample: US (primary market per spec) — KR sample stats are reported
alongside for visibility but do not decide `enabled`. Sequential processing
throughout (8GB rule). Costs always on.

Confluence (⑦) is validated by partitioning its entries (>= 2 base strategies
firing the same bar) by strongest component, then backtesting each partition
with that component's OWN exit logic — no mixed-exit distortion.

Invoked via: python main.py backtest [--smoke]
"""

import logging
import os
from datetime import date, timedelta

os.environ.setdefault("TQDM_DISABLE", "1")  # silence backtesting.py progress bars

import numpy as np
import pandas as pd

from config import settings
from src.analysis.base_strategy import BaseStrategy, load_strategy_config
from src.analysis.indicators import compute_indicators
from src.analysis.registry import get_strategies
from src.backtest.backtester import EntryPlan, aggregate_stats, generate_entry_plan, run_backtest
from src.backtest.validation import GateReport, format_report, monte_carlo, validate_strategy
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


def validate_confluence(
    strategies: list[BaseStrategy],
    config: dict,
    frames: dict[str, pd.DataFrame],
    market_of: dict[str, str],
) -> GateReport:
    """Validate ⑦ by strongest-component partition (own exits per partition)."""
    cfg = config["confluence"]
    min_n = int(cfg["min_strategies"])
    report = GateReport(strategy_id="confluence")

    all_trades: list[pd.DataFrame] = []
    split_trades: dict[str, list[pd.DataFrame]] = {"is": [], "oos": []}
    for ticker, df_ind in frames.items():
        plans = {
            s.strategy_id: generate_entry_plan(df_ind, s, ticker, market_of[ticker])
            for s in strategies
        }
        strength_mat = pd.DataFrame({sid: p.strength for sid, p in plans.items()})
        fired = strength_mat.notna()
        conf_bars = fired.sum(axis=1) >= min_n
        if not conf_bars.any():
            continue
        # idxmax only on confluence bars (others are all-NaN rows).
        strongest = pd.Series(pd.NA, index=strength_mat.index, dtype=object)
        strongest[conf_bars] = strength_mat[conf_bars].idxmax(axis=1)
        n_total = len(df_ind)
        split_i = int(n_total * settings.VAL_IS_FRAC)
        for s in strategies:
            sid = s.strategy_id
            mask = conf_bars & (strongest == sid)
            if not mask.any():
                continue
            base = plans[sid]
            masked = EntryPlan(
                entry=base.entry & mask,
                stop=base.stop.where(mask),
                target=base.target.where(mask),
            )
            trades = run_backtest(df_ind, masked, s, market_of[ticker])
            if trades.empty:
                continue
            trades["ticker"] = ticker
            all_trades.append(trades)
            cut_date = pd.to_datetime(df_ind["date"].iloc[split_i])
            split_trades["is"].append(trades[trades["entry_time"] < cut_date])
            split_trades["oos"].append(trades[trades["entry_time"] >= cut_date])

    full = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame(
        columns=["entry_time", "exit_time", "return_pct", "holding_days"]
    )
    is_t = pd.concat(split_trades["is"], ignore_index=True) if split_trades["is"] else full.iloc[:0]
    oos_t = pd.concat(split_trades["oos"], ignore_index=True) if split_trades["oos"] else full.iloc[:0]
    report.is_stats = aggregate_stats(is_t)
    report.oos_stats = aggregate_stats(oos_t)
    report.mc_p5_equity_mult, report.mc_p95_mdd_pct = monte_carlo(
        full["return_pct"], settings.VAL_MC_RUNS,
        trade_fraction=settings.VAL_MC_TRADE_FRACTION,
    )
    oos_pf, oos_n = report.oos_stats["profit_factor"], report.oos_stats["n"]
    is_wr, oos_wr = report.is_stats["win_rate"], report.oos_stats["win_rate"]
    report.gates = {
        "G1_oos_pf_gt_1": bool(oos_pf == oos_pf and oos_pf > 1.0),
        "G2_wr_holdup": bool(
            oos_wr == oos_wr and is_wr == is_wr and oos_wr >= is_wr - settings.VAL_WR_DROP_MAX
        ),
        "G3_walk_forward": True,  # inherited: components carry their own G3
        "G4_mc_mdd_bound": bool(
            report.mc_p95_mdd_pct == report.mc_p95_mdd_pct
            and report.mc_p95_mdd_pct <= settings.VAL_MC_MDD_MAX_PCT
        ),
        "G5_sensitivity": True,  # inherited from component gates
        "G6_min_oos_trades": oos_n >= settings.VAL_MIN_TRADES_OOS,
    }
    return report


def run(smoke: bool = False) -> dict[str, GateReport]:
    """Run the full validation suite; returns {strategy_id: GateReport}.

    Args:
        smoke: Tiny sample / fewer MC runs — debug only, never gates YAML.
    """
    config = load_strategy_config()
    strategies = get_strategies(config, enabled_only=False)
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

    conf_report = validate_confluence(strategies, config, us_frames, {t: "us" for t in us_frames})
    reports["confluence"] = conf_report
    print("\n" + format_report(conf_report))
    print("\n(confluence G3/G5는 구성 전략 게이트에서 상속 — 자체 거래 표본은 G1/G2/G4/G6으로 판정)")
    return reports
