"""One-off: recompute G4 Monte Carlo under fractional sizing for transparency.

Compares per-trade sizing assumptions on the same bootstrap (full-size 100%
vs realistic 10% of equity per trade) for the two strategies whose verdict
G4 decides (breakout, wyckoff_spring). Prints both — no gate is changed here.
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("TQDM_DISABLE", "1")

import numpy as np
import pandas as pd

from config import settings
from src.analysis.base_strategy import load_strategy_config
from src.analysis.registry import get_strategies
from src.backtest.backtester import generate_entry_plan, run_backtest
from src.backtest.run_validation import build_frames

logging.basicConfig(level=logging.WARNING)


def mc_both(returns: pd.Series, runs: int = 1000, fraction: float = 0.10) -> dict[str, float]:
    r = returns.to_numpy()
    rng = np.random.default_rng(42)
    out = {}
    for label, scale in (("full_100pct", 1.0), (f"frac_{int(fraction * 100)}pct", fraction)):
        finals, mdds = np.empty(runs), np.empty(runs)
        for k in range(runs):
            sample = rng.choice(r, size=len(r), replace=True) * scale
            equity = np.cumprod(1.0 + sample)
            peak = np.maximum.accumulate(equity)
            mdds[k] = ((equity - peak) / peak).min()
            finals[k] = equity[-1]
        out[label] = {
            "p5_final": float(np.percentile(finals, 5)),
            "p95_mdd_pct": float(-np.percentile(mdds, 5) * 100),
        }
    return out


def main() -> None:  # noqa: D103
    config = load_strategy_config()
    frames = build_frames("us", settings.VAL_SAMPLE_US)
    for sid in ("breakout", "wyckoff_spring"):
        strategy = next(s for s in get_strategies(config, enabled_only=False) if s.strategy_id == sid)
        trades = []
        for t, df in frames.items():
            plan = generate_entry_plan(df, strategy, t, "us")
            tr = run_backtest(df, plan, strategy, "us")
            if not tr.empty:
                trades.append(tr)
        all_tr = pd.concat(trades, ignore_index=True)
        res = mc_both(all_tr["return_pct"])
        print(f"\n[{sid}] n_trades={len(all_tr)}")
        for label, v in res.items():
            verdict = "PASS" if v["p95_mdd_pct"] <= settings.VAL_MC_MDD_MAX_PCT else "FAIL"
            print(f"  {label:>13}: 5%ile final x{v['p5_final']:.2f}, worst-tail MDD {v['p95_mdd_pct']:.1f}% -> G4 {verdict} (bound {settings.VAL_MC_MDD_MAX_PCT}%)")


if __name__ == "__main__":
    main()
