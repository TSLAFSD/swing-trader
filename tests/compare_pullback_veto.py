"""Part 2b (2026-07-07): pullback baseline vs distribution-veto variants.

Pre-registered grid: dist_veto_bars in {5, 10} — fixed BEFORE results.
Selection is informational only; pullback is DISABLED and any enablement
requires the FULL Phase-4 gates (main.py backtest --strategy pullback with
the chosen param in YAML-candidate form). Survivorship bias applies.

Invoked via: .venv/bin/python tests/compare_pullback_veto.py
"""

import copy
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from config import settings
from src.analysis.base_strategy import load_strategy_config
from src.analysis.strategy_pullback import PullbackStrategy
from src.backtest.backtester import generate_entry_plan
from src.backtest.run_validation import build_frames
from src.backtest.validation import _collect_trades, aggregate_stats

logging.basicConfig(level=logging.WARNING)

GRID = [None, 5, 10]  # None = baseline


def main() -> None:  # noqa: D103
    frames = build_frames("us", settings.VAL_SAMPLE_US)
    market_of = {t: "us" for t in frames}
    all_dates = sorted({d for df in frames.values() for d in pd.to_datetime(df["date"]).dt.date})
    lo, hi = all_dates[0], all_dates[-1]
    split = all_dates[int(len(all_dates) * settings.VAL_IS_FRAC)]
    print(f"pullback veto grid — US sample {len(frames)} · 생존 편향 주의, 과거 성과")
    print(f"{'variant':<22}{'OoS n':>8}{'OoS WR':>9}{'OoS PF':>9}{'IS PF':>8}")
    for veto in GRID:
        config = copy.deepcopy(load_strategy_config())
        config["strategies"]["pullback"]["params"].pop("dist_veto_bars", None)
        if veto is not None:
            config["strategies"]["pullback"]["params"]["dist_veto_bars"] = veto
        strategy = PullbackStrategy(config)
        plans = {t: generate_entry_plan(df, strategy, t, market_of[t]) for t, df in frames.items()}
        oos = aggregate_stats(_collect_trades(frames, plans, strategy, market_of, split, hi))
        ins = aggregate_stats(_collect_trades(frames, plans, strategy, market_of, lo, split))
        name = "baseline" if veto is None else f"dist_veto_bars={veto}"
        print(
            f"{name:<22}{oos['n']:>8}{oos['win_rate'] * 100:>8.1f}%"
            f"{oos['profit_factor']:>9.2f}{ins['profit_factor']:>8.2f}"
        )


if __name__ == "__main__":
    main()
