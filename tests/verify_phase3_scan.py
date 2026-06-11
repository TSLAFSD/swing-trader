"""Phase 3 verification: real-data scan demo on ~200 US + ~50 KR tickers.

Fetches 2y history into the store, runs the full signal engine with ALL
strategies (enabled_only=False — YAML flags stay false until Phase 4 gates),
prints a markdown signal table plus summarize_kr output for the top signal.

Run from repo root: .venv/bin/python tests/verify_phase3_scan.py
"""

import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.analysis.signal_engine import scan_market
from src.analysis.summarize_kr import summarize_kr
from src.analysis import indicators as ind
from src.data.kr_fetcher import fetch_kr_ohlcv
from src.data.store import ParquetStore
from src.data.universe import load_kr_universe, load_us_universe
from src.data.us_fetcher import fetch_us_ohlcv

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logging.getLogger("src.analysis.signal_engine").setLevel(logging.WARNING)
logger = logging.getLogger("verify3")

N_US, N_KR = 200, 50


def main() -> None:  # noqa: D103
    store = ParquetStore()
    start = date.today() - timedelta(days=730)

    us_uni = load_us_universe(refresh=False)
    us_tickers = us_uni["ticker"].head(N_US).tolist()
    logger.info("fetching %d US tickers (2y)...", len(us_tickers))
    t0 = time.time()
    us = fetch_us_ohlcv(us_tickers, start=start)
    logger.info("US fetch: %d rows in %.0fs", len(us), time.time() - t0)
    store.upsert(us, "us")

    kr_uni = load_kr_universe()
    kr_head = kr_uni[kr_uni["market"] == "KOSPI"].head(N_KR)
    kr_tickers = kr_head["ticker"].tolist()
    kr_markets = dict(zip(kr_head["ticker"], kr_head["market"]))
    logger.info("fetching %d KR tickers (2y, sequential)...", len(kr_tickers))
    t0 = time.time()
    kr, kr_sources = fetch_kr_ohlcv(kr_tickers, start=start, markets=kr_markets)
    logger.info(
        "KR fetch: %d rows in %.0fs; sources: %s",
        len(kr), time.time() - t0, pd.Series(kr_sources).value_counts().to_dict(),
    )
    store.upsert(kr, "kr")

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
        if result.signals:
            print(f"\n| # | 종목 | 전략 | 강도 | 가격 | 손절 | 목표 | RS%ile | 근거 |")
            print("|---|------|------|------|------|------|------|--------|------|")
            for i, s in enumerate(result.signals, 1):
                tp = f"{s.suggested_take_profit:,.2f}" if s.suggested_take_profit else "ATR추적"
                rs = s.indicators.get("rs_percentile", "—")
                tags = " ".join(s.tags)
                print(f"| {i} | {s.name}({s.ticker}) | {s.strategy_id} | {s.strength} "
                      f"| {s.price:,.2f} | {s.suggested_stop_loss:,.2f} | {tp} | {rs} "
                      f"| {s.reason} {tags} |")
            top = result.signals[0]
            frame = data[data["ticker"] == top.ticker].sort_values("date").reset_index(drop=True)
            row = ind.compute_indicators(frame).iloc[-1]
            print(f"\n[summarize_kr — {top.name}({top.ticker})]")
            for line in summarize_kr(row, market):
                print(f"  · {line}")
        else:
            print("(시그널 없음)")

    print("\n--- PHASE 3 SCAN DEMO DONE ---")


if __name__ == "__main__":
    main()
