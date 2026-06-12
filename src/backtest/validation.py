"""Strategy validation gates (spec §7 Layer 1) — controls YAML `enabled`.

Per strategy, over a representative universe sample with costs always on:
  G1 IS/OoS      — 70/30 time split; OoS profit factor > 1.0 after costs.
  G2 WR hold-up  — OoS win rate >= IS win rate - 10%p.
  G3 Walk-forward— PF > 1.0 in >= 2 of 3 rolling validate windows.
  G4 Monte Carlo — >= 1000 trade-order bootstraps; worst-tail (95th pct) MDD
                   within bound; 5th pct final equity reported.
  G5 Sensitivity — key params perturbed +-20%; PF must not collapse.
  G6 Sample size — OoS trades >= VAL_MIN_TRADES_OOS (else verdict meaningless).
Regime-sliced stats and index buy&hold benchmark are REPORTED alongside
(visibility, not gates). Borderline = disabled, stated honestly.

HONESTY: results are historical; the sample is the CURRENT universe
(survivorship bias — delisted tickers absent, so stats are optimistic).
"""

import copy
import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from config import settings
from src.analysis.base_strategy import BaseStrategy
from src.backtest.backtester import EntryPlan, aggregate_stats, generate_entry_plan, run_backtest

logger = logging.getLogger(__name__)

# Key entry parameters perturbed in G5, per strategy ("a.b" = nested path).
SENSITIVITY_PARAMS: dict[str, list[str]] = {
    "pullback": ["rsi_max", "adx_min"],
    "zscore_meanrev": ["z_entry", "vol_mult"],
    "connors_rsi2": ["rsi2_entry"],
    "breakout": ["vol_mult", "adx_min"],
    "squeeze": ["vol_mult", "squeeze_min_days"],
    "wyckoff_spring": ["vpa.vol_mult", "vpa.exhaust_ratio"],
}


def _perturb_param(params: dict, path: str, mult: float) -> None:
    """Multiply a (possibly nested, dot-separated) numeric param in place."""
    node = params
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[key]
    original = node[keys[-1]]
    node[keys[-1]] = type(original)(original * mult)


@dataclass
class GateReport:
    """Full validation outcome for one strategy."""

    strategy_id: str
    is_stats: dict[str, float] = field(default_factory=dict)
    oos_stats: dict[str, float] = field(default_factory=dict)
    walk_forward: list[dict[str, float]] = field(default_factory=list)
    mc_p5_equity_mult: float = float("nan")
    mc_p95_mdd_pct: float = float("nan")
    sensitivity: list[dict[str, float | str]] = field(default_factory=list)
    regime_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    benchmark_return_pct: float = float("nan")
    gates: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """All gates green."""
        return bool(self.gates) and all(self.gates.values())


def _slice_by_date(df_ind: pd.DataFrame, plan: EntryPlan, start: date, end: date) -> tuple[pd.DataFrame, EntryPlan]:
    """Slice an indicator frame + aligned plan to [start, end]."""
    dates = pd.to_datetime(df_ind["date"]).dt.date
    mask = (dates >= start) & (dates <= end)
    idx = df_ind.index[mask]
    return (
        df_ind.loc[idx].reset_index(drop=True),
        EntryPlan(
            entry=plan.entry.loc[idx].reset_index(drop=True),
            stop=plan.stop.loc[idx].reset_index(drop=True),
            target=plan.target.loc[idx].reset_index(drop=True),
            strength=plan.strength.loc[idx].reset_index(drop=True) if plan.strength is not None else None,
        ),
    )


def _collect_trades(
    frames: dict[str, pd.DataFrame],
    plans: dict[str, EntryPlan],
    strategy: BaseStrategy,
    market_of: dict[str, str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Backtest every ticker on a date window; concatenate trades."""
    all_trades: list[pd.DataFrame] = []
    for ticker, df_ind in frames.items():  # sequential (8GB rule)
        sliced_df, sliced_plan = _slice_by_date(df_ind, plans[ticker], start, end)
        if len(sliced_df) < 30 or not sliced_plan.entry.any():
            continue
        trades = run_backtest(sliced_df, sliced_plan, strategy, market_of[ticker])
        if not trades.empty:
            trades["ticker"] = ticker
            all_trades.append(trades)
    if not all_trades:
        return pd.DataFrame(columns=["entry_time", "exit_time", "return_pct", "holding_days", "ticker"])
    return pd.concat(all_trades, ignore_index=True)


def monte_carlo(
    returns: pd.Series, runs: int, seed: int = 42, trade_fraction: float = 1.0
) -> tuple[float, float]:
    """Bootstrap the trade sequence; return (p5 final equity mult, p95 MDD %).

    Shuffling/bootstrapping breaks any lucky ordering — a strategy whose
    nominal equity curve depends on sequence fails the MDD bound here.

    Args:
        returns: Per-trade return fractions.
        runs: Bootstrap path count.
        seed: RNG seed (deterministic gates).
        trade_fraction: Equity fraction per trade (1.0 = full rotation;
            gates use settings.VAL_MC_TRADE_FRACTION — owner-approved
            realistic sizing).
    """
    r = returns.to_numpy()
    if len(r) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    finals = np.empty(runs)
    mdds = np.empty(runs)
    for k in range(runs):
        sample = rng.choice(r, size=len(r), replace=True) * trade_fraction
        equity = np.cumprod(1.0 + sample)
        peak = np.maximum.accumulate(equity)
        mdds[k] = ((equity - peak) / peak).min()
        finals[k] = equity[-1]
    return float(np.percentile(finals, 5)), float(-np.percentile(mdds, 5) * 100.0)


def regime_series(index_close: pd.Series) -> pd.Series:
    """Classify each date bull/bear/sideways via index vs SMA60 + slope."""
    sma = index_close.rolling(60).mean()
    slope = sma.diff(20)
    out = pd.Series("sideways", index=index_close.index)
    out[(index_close > sma) & (slope > 0)] = "bull"
    out[(index_close < sma) & (slope < 0)] = "bear"
    return out


def validate_strategy(
    strategy_cls: type[BaseStrategy],
    base_config: dict,
    frames: dict[str, pd.DataFrame],
    market_of: dict[str, str],
    index_close: pd.Series,
) -> GateReport:
    """Run every gate for one strategy and return the full report.

    Args:
        strategy_cls: Strategy class (instantiated per config variant).
        base_config: strategies.yaml dict.
        frames: {ticker: indicator frame, full history}.
        market_of: {ticker: "us"|"kr"}.
        index_close: Benchmark index close series (datetime index).

    Returns:
        GateReport with stats, per-gate verdicts and `.passed`.
    """
    strategy = strategy_cls(base_config)
    sid = strategy.strategy_id
    report = GateReport(strategy_id=sid)

    logger.info("[%s] generating entry plans for %d tickers...", sid, len(frames))
    plans = {
        t: generate_entry_plan(df, strategy, t, market_of[t]) for t, df in frames.items()
    }

    all_dates = sorted(
        {d for df in frames.values() for d in pd.to_datetime(df["date"]).dt.date}
    )
    lo, hi = all_dates[0], all_dates[-1]
    split = all_dates[int(len(all_dates) * settings.VAL_IS_FRAC)]

    # G1/G2: IS / OoS
    is_trades = _collect_trades(frames, plans, strategy, market_of, lo, split)
    oos_trades = _collect_trades(frames, plans, strategy, market_of, split, hi)
    report.is_stats = aggregate_stats(is_trades)
    report.oos_stats = aggregate_stats(oos_trades)

    # G3: walk-forward windows (rolling validate slices over the full span).
    n_win = settings.VAL_WF_WINDOWS
    bounds = [all_dates[int(len(all_dates) * k / n_win)] for k in range(n_win)] + [hi]
    for k in range(n_win):
        w_trades = _collect_trades(frames, plans, strategy, market_of, bounds[k], bounds[k + 1])
        report.walk_forward.append(aggregate_stats(w_trades))

    # G4: Monte Carlo on the FULL trade list.
    nonempty = [t for t in (is_trades, oos_trades) if not t.empty]
    full_trades = (
        pd.concat(nonempty, ignore_index=True) if nonempty else is_trades.iloc[:0]
    )
    report.mc_p5_equity_mult, report.mc_p95_mdd_pct = monte_carlo(
        full_trades["return_pct"], settings.VAL_MC_RUNS,
        trade_fraction=settings.VAL_MC_TRADE_FRACTION,
    )

    # G5: parameter sensitivity on a ticker sub-sample.
    sens_tickers = list(frames)[: settings.VAL_SENS_TICKERS]
    sens_frames = {t: frames[t] for t in sens_tickers}
    base_sub = _collect_trades(sens_frames, plans, strategy, market_of, lo, hi)
    base_pf = aggregate_stats(base_sub)["profit_factor"]
    sens_ok = True
    for param in SENSITIVITY_PARAMS.get(sid, []):
        for mult in (1 - settings.VAL_SENS_PERTURB, 1 + settings.VAL_SENS_PERTURB):
            cfg = copy.deepcopy(base_config)
            _perturb_param(cfg["strategies"][sid]["params"], param, mult)
            perturbed = strategy_cls(cfg)
            p_plans = {
                t: generate_entry_plan(df, perturbed, t, market_of[t])
                for t, df in sens_frames.items()
            }
            p_trades = _collect_trades(sens_frames, p_plans, perturbed, market_of, lo, hi)
            p_pf = aggregate_stats(p_trades)["profit_factor"]
            ok = (
                not np.isnan(p_pf)
                and (np.isnan(base_pf) or p_pf >= settings.VAL_SENS_PF_RATIO_MIN * base_pf)
                and p_pf >= settings.VAL_SENS_PF_ABS_MIN
            )
            sens_ok = sens_ok and ok
            report.sensitivity.append(
                {"param": param, "mult": round(mult, 2), "pf": round(p_pf, 3) if p_pf == p_pf else float("nan"), "ok": ok}
            )

    # Regime-sliced stats (reported, not gated).
    regimes = regime_series(index_close)
    if not full_trades.empty:
        trade_regime = full_trades["entry_time"].map(
            lambda t: regimes.asof(t) if t >= regimes.index[0] else "sideways"
        )
        for label in ("bull", "bear", "sideways"):
            sub = full_trades[trade_regime == label]
            report.regime_stats[label] = aggregate_stats(sub)

    # Benchmark: index buy & hold over the same span.
    span = index_close[(index_close.index.date >= lo) & (index_close.index.date <= hi)]
    if len(span) > 1:
        report.benchmark_return_pct = float((span.iloc[-1] / span.iloc[0] - 1) * 100)

    is_wr, oos_wr = report.is_stats["win_rate"], report.oos_stats["win_rate"]
    oos_pf, oos_n = report.oos_stats["profit_factor"], report.oos_stats["n"]
    wf_pass = sum(1 for w in report.walk_forward if w["n"] > 0 and w["profit_factor"] > 1.0)
    report.gates = {
        "G1_oos_pf_gt_1": bool(oos_pf == oos_pf and oos_pf > 1.0),
        "G2_wr_holdup": bool(
            oos_wr == oos_wr and is_wr == is_wr and oos_wr >= is_wr - settings.VAL_WR_DROP_MAX
        ),
        "G3_walk_forward": wf_pass >= settings.VAL_WF_MIN_PASS,
        "G4_mc_mdd_bound": bool(
            report.mc_p95_mdd_pct == report.mc_p95_mdd_pct
            and report.mc_p95_mdd_pct <= settings.VAL_MC_MDD_MAX_PCT
        ),
        "G5_sensitivity": sens_ok,
        "G6_min_oos_trades": oos_n >= settings.VAL_MIN_TRADES_OOS,
    }
    logger.info("[%s] gates: %s -> %s", sid, report.gates, "PASS" if report.passed else "FAIL")
    return report


def format_report(report: GateReport) -> str:
    """Render one strategy's gate report as a markdown block."""
    g = report.gates
    mark = lambda ok: "✅" if ok else "❌"  # noqa: E731
    lines = [
        f"### {report.strategy_id} — {'PASS → enabled' if report.passed else 'FAIL → disabled'}",
        f"| metric | IS | OoS |",
        f"|---|---|---|",
        f"| trades | {report.is_stats['n']} | {report.oos_stats['n']} |",
        f"| win rate | {report.is_stats['win_rate'] * 100:.1f}% | {report.oos_stats['win_rate'] * 100:.1f}% |"
        if report.is_stats["n"] and report.oos_stats["n"]
        else "| win rate | — | — |",
        f"| profit factor | {report.is_stats['profit_factor']:.2f} | {report.oos_stats['profit_factor']:.2f} |"
        if report.is_stats["n"] and report.oos_stats["n"]
        else "| profit factor | — | — |",
        f"- walk-forward PF: "
        + ", ".join(
            f"W{i + 1}={w['profit_factor']:.2f}(n={w['n']})" if w["n"] else f"W{i + 1}=—(n=0)"
            for i, w in enumerate(report.walk_forward)
        ),
        f"- Monte Carlo({settings.VAL_MC_RUNS}): 5%ile final equity x{report.mc_p5_equity_mult:.2f}, "
        f"worst-tail MDD {report.mc_p95_mdd_pct:.1f}%",
        f"- sensitivity: "
        + (
            ", ".join(
                f"{s['param']}x{s['mult']}→PF {s['pf'] if s['pf'] == s['pf'] else '—'}{'✓' if s['ok'] else '✗'}"
                for s in report.sensitivity
            )
            or "—"
        ),
        f"- regimes: "
        + ", ".join(
            f"{k}: n={v['n']}, PF={v['profit_factor']:.2f}" if v["n"] else f"{k}: n=0"
            for k, v in report.regime_stats.items()
        ),
        f"- benchmark (index B&H same span): {report.benchmark_return_pct:+.1f}%",
        f"- gates: " + " ".join(f"{mark(ok)}{name}" for name, ok in g.items()),
    ]
    return "\n".join(lines)
