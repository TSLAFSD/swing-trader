"""Re-run the Phase 3 scan demo against already-stored data (no refetch)."""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis import indicators as ind
from src.analysis.signal_engine import scan_market
from src.analysis.summarize_kr import summarize_kr
from src.data.store import ParquetStore
from src.data.universe import load_kr_universe, load_us_universe

logging.basicConfig(level=logging.WARNING)


def main() -> None:  # noqa: D103
    store = ParquetStore()
    us_uni = load_us_universe(refresh=False)
    kr_uni = load_kr_universe()
    for market, names_df in (("us", us_uni), ("kr", kr_uni)):
        names = dict(zip(names_df["ticker"], names_df["name"]))
        data = store.load(market)
        t0 = time.time()
        result = scan_market(market, data, names, enabled_only=False)
        elapsed = time.time() - t0
        print(f"\n{'=' * 78}")
        print(f"[{market.upper()} SCAN] {result.scan_date} — {result.total_scanned} scanned "
              f"in {elapsed:.0f}s, {len(result.signals)} signals, "
              f"breadth {result.breadth_pct:.1f}%, anomalies {result.anomalies}, "
              f"rs_dropped {result.rs_dropped}")
        if result.regime:
            print(f"국면: {result.regime.label_kr} (downgrade x{result.regime.downgrade_factor})")
        for i, s in enumerate(result.signals, 1):
            tp = f"{s.suggested_take_profit:,.2f}" if s.suggested_take_profit else "ATR추적"
            rs = s.indicators.get("rs_percentile", "—")
            print(f"| {i} | {s.name}({s.ticker}) | {s.strategy_id} | {s.strength} "
                  f"| {s.price:,.2f} | SL {s.suggested_stop_loss:,.2f} | TP {tp} | RS {rs} "
                  f"| {s.reason} {' '.join(s.tags)}")
        if result.signals:
            top = result.signals[0]
            frame = data[data["ticker"] == top.ticker].sort_values("date").reset_index(drop=True)
            row = ind.compute_indicators(frame).iloc[-1]
            print(f"\n[summarize_kr — {top.name}({top.ticker})]")
            for line in summarize_kr(row, market):
                print(f"  · {line}")
        else:
            print("(시그널 없음)")
    print("\n--- RERUN DONE ---")


if __name__ == "__main__":
    main()
