"""Part 1 (2026-07-07): full Phase-4 gates for breakout WITH max_ext_pct=15.

Owner-approved selection criterion (2026-07-07, POST-HOC — defined after the
2026-07-02 grid results were known; disclosed per reporting-integrity):
    OoS PF >= baseline x1.05 AND OoS WR >= baseline -1%p AND OoS n >= x0.7
Sole passer on that grid: max_ext_pct=15. This script is the ADOPTION gate:
the guarded breakout must re-pass every Phase-4 gate before YAML changes.

Results are historical; survivorship bias applies (current universe only).
Invoked via: .venv/bin/python tests/validate_breakout_guard.py
"""

import copy
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from src.analysis.base_strategy import load_strategy_config
from src.analysis.strategy_breakout import BreakoutStrategy
from src.backtest.run_validation import build_frames, fetch_index_series
from src.backtest.validation import format_report, validate_strategy

logging.basicConfig(level=logging.INFO)


def main() -> None:  # noqa: D103
    config = copy.deepcopy(load_strategy_config())
    config["strategies"]["breakout"]["params"]["max_ext_pct"] = 15.0
    frames = build_frames("us", settings.VAL_SAMPLE_US)
    index = fetch_index_series("us", settings.HISTORY_YEARS)
    print(f"breakout + max_ext_pct=15 — US sample {len(frames)} (GATING)")
    print("주의: 생존 편향(현재 유니버스 기준) — 결과는 과거 성과이며 미래 보장 없음")
    report = validate_strategy(
        BreakoutStrategy, config, frames, {t: "us" for t in frames}, index
    )
    print(format_report(report))


if __name__ == "__main__":
    main()
