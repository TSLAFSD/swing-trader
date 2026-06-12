"""U2 verification: per-stage Wyckoff VPA detection frequency, full universe.

Restores the data branch (full runner-scanned universe), then runs the
3-stage buy-side pipeline per ticker (sequential, raw OHLCV only — no
pandas-ta needed). Reports counts per stage and per market.
"""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.analysis.base_strategy import load_strategy_config
from src.analysis.wyckoff_vpa import (
    detect_liquidity_low,
    detect_selling_climax,
    detect_supply_exhaustion,
    weis_waves,
)
from src.data.store import ParquetStore, restore_from_data_branch

logging.basicConfig(level=logging.WARNING)

VPA = load_strategy_config()["strategies"]["wyckoff_spring"]["params"]["vpa"]


def main() -> None:  # noqa: D103
    restore_from_data_branch()
    store = ParquetStore()
    for market in ("us", "kr"):
        data = store.load(market)
        if data.empty:
            print(f"[{market}] no data")
            continue
        t0 = time.time()
        n_total = n_level = n_climax = n_exhaustion = 0
        examples: list[str] = []
        for ticker, df in data.groupby("ticker"):
            df = df.sort_values("date").reset_index(drop=True)
            if len(df) < 120:
                continue
            n_total += 1
            level = detect_liquidity_low(
                df, lookback=VPA["lookback"], pivot_strength=VPA["pivot_strength"],
                equal_low_pct=VPA["equal_low_pct"],
            )
            if level is None:
                continue
            n_level += 1
            climax = detect_selling_climax(
                df, level.level, vol_ma_days=VPA["vol_ma_days"],
                vol_mult=VPA["vol_mult"], wick_body_ratio=VPA["wick_body_ratio"],
            )
            if climax is None:
                continue
            n_climax += 1
            waves = weis_waves(df, zigzag_pct=VPA["zigzag_pct"])
            exhaustion = detect_supply_exhaustion(
                waves, climax, retest_window=VPA["retest_window"],
                exhaust_ratio=VPA["exhaust_ratio"],
            )
            if exhaustion is not None:
                n_exhaustion += 1
                if len(examples) < 5:
                    examples.append(
                        f"{ticker}: level {level.level:,.0f}({level.touch_count}touch) "
                        f"climax {climax.sweep_date}(vol x{climax.volume_ratio:.1f}, "
                        f"{climax.recovery_type}) retest ratio {exhaustion.test_volume_ratio:.2f}"
                    )
        elapsed = time.time() - t0
        print(f"\n[{market.upper()}] {n_total} tickers in {elapsed:.0f}s")
        print(f"  1단계 유동성 레벨 확정: {n_level} ({n_level / n_total * 100:.1f}%)")
        print(f"  2단계 셀링 클라이맥스:   {n_climax} ({n_climax / n_total * 100:.1f}%)")
        print(f"  3단계 공급 고갈(전체 충족): {n_exhaustion} ({n_exhaustion / n_total * 100:.1f}%)")
        for ex in examples:
            print(f"    예시 — {ex}")


if __name__ == "__main__":
    main()
