"""Part B: breakout overheat-guard comparison (baseline vs guard variants).

Pre-registered adoption criterion (docs/superpowers/specs/2026-07-02-*.md —
DO NOT tune after seeing results):
    OoS win rate >= baseline + 3 %p
    AND OoS PF >= baseline PF x 0.9
    AND OoS trade count >= baseline n x 0.7

Small fixed grid (3 guard types x 3 values) to limit data-mining surface.
US sample gates (primary market); results are historical — no future
guarantee, survivorship bias applies (current universe only).

Invoked via: .venv/bin/python tests/compare_breakout_guards.py
"""

import copy
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from config import settings
from src.analysis.base_strategy import load_strategy_config
from src.analysis.strategy_breakout import BreakoutStrategy
from src.backtest.backtester import generate_entry_plan
from src.backtest.run_validation import build_frames
from src.backtest.validation import _collect_trades, aggregate_stats

logging.basicConfig(level=logging.WARNING)

# Pre-registered grid — fixed BEFORE any result is observed.
GRID: list[tuple[str, float]] = [
    ("max_ext_atr", 2.0), ("max_ext_atr", 3.0), ("max_ext_atr", 4.0),
    ("max_ext_pct", 10.0), ("max_ext_pct", 15.0), ("max_ext_pct", 20.0),
    ("rsi_max", 70.0), ("rsi_max", 75.0), ("rsi_max", 80.0),
]
WR_MIN_GAIN_PP = 3.0
PF_FLOOR_RATIO = 0.9
N_FLOOR_RATIO = 0.7


def run_variant(config: dict, frames: dict, market_of: dict, lo, split, hi) -> dict:
    """IS/OoS stats for one breakout config over the shared frames."""
    strategy = BreakoutStrategy(config)
    plans = {t: generate_entry_plan(df, strategy, t, market_of[t]) for t, df in frames.items()}
    oos = aggregate_stats(_collect_trades(frames, plans, strategy, market_of, split, hi))
    ins = aggregate_stats(_collect_trades(frames, plans, strategy, market_of, lo, split))
    return {"is": ins, "oos": oos}


def main() -> None:  # noqa: D103
    frames = build_frames("us", settings.VAL_SAMPLE_US)
    market_of = {t: "us" for t in frames}
    all_dates = sorted({d for df in frames.values() for d in pd.to_datetime(df["date"]).dt.date})
    lo, hi = all_dates[0], all_dates[-1]
    split = all_dates[int(len(all_dates) * settings.VAL_IS_FRAC)]

    base_cfg = load_strategy_config()
    base = run_variant(base_cfg, frames, market_of, lo, split, hi)
    b_oos = base["oos"]
    print(f"US 표본 {len(frames)}종목 · IS {lo}~{split} · OoS {split}~{hi}")
    print("주의: 생존 편향(현재 유니버스) — 과거 성과이며 미래 보장 아님\n")
    print(f"{'variant':<22} {'OoS n':>6} {'OoS WR':>8} {'OoS PF':>8} {'IS PF':>8}  verdict")
    print(f"{'baseline':<22} {b_oos['n']:>6} {b_oos['win_rate']*100:>7.1f}% "
          f"{b_oos['profit_factor']:>8.2f} {base['is']['profit_factor']:>8.2f}  —")

    for key, val in GRID:
        cfg = copy.deepcopy(base_cfg)
        cfg["strategies"]["breakout"]["params"][key] = val
        r = run_variant(cfg, frames, market_of, lo, split, hi)
        o = r["oos"]
        ok = (
            o["n"] >= b_oos["n"] * N_FLOOR_RATIO
            and o["win_rate"] * 100 >= b_oos["win_rate"] * 100 + WR_MIN_GAIN_PP
            and o["profit_factor"] == o["profit_factor"]  # NaN-safe
            and o["profit_factor"] >= b_oos["profit_factor"] * PF_FLOOR_RATIO
        )
        print(f"{f'{key}={val:g}':<22} {o['n']:>6} {o['win_rate']*100:>7.1f}% "
              f"{o['profit_factor']:>8.2f} {r['is']['profit_factor']:>8.2f}  "
              f"{'✅ 채택 후보' if ok else '❌ 기준 미달'}")


if __name__ == "__main__":
    main()
