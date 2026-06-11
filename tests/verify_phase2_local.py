"""Phase 2 local verification (a) + (e): fetches, store round-trip, adjustment.

Run from repo root: .venv/bin/python tests/verify_phase2_local.py
"""

import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from config import settings
from src.data.kr_fetcher import _fetch_pykrx, _fetch_yfinance_kr, fetch_kr_ohlcv
from src.data.store import ParquetStore
from src.data.universe import load_kr_universe, load_us_universe
from src.data.us_fetcher import fetch_us_ohlcv
from src.data.fundamentals import fetch_fundamentals

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("verify")

pd.set_option("display.width", 140)


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n[{title}]\n{'=' * 70}")


def main() -> None:  # noqa: D103
    store = ParquetStore()
    start = date(2023, 6, 12)  # ~3y

    section("(a-1) US: AAPL 3y via yfinance")
    us = fetch_us_ohlcv(["AAPL"], start=start)
    print(us.head(3).to_string(), "\n...\n", us.tail(3).to_string())
    print(f"rows={len(us)}  range={us['date'].min()} → {us['date'].max()}")
    store.upsert(us, "us")

    section("(a-2) KR: 005930 (삼성전자) 3y via triple-source chain")
    kr, sources = fetch_kr_ohlcv(["005930"], start=start, markets={"005930": "KOSPI"})
    print(kr.head(3).to_string(), "\n...\n", kr.tail(3).to_string())
    print(f"rows={len(kr)}  range={kr['date'].min()} → {kr['date'].max()}  sources={sources}")
    store.upsert(kr, "kr")

    section("(a-3) Store round-trip / cache hit via DuckDB")
    cached = store.load("us", tickers=["AAPL"], start=date(2026, 6, 1))
    print(cached.tail(3).to_string())
    print(f"cache hit: {len(cached)} rows for AAPL since 2026-06-01")
    print(f"last_date(us, AAPL) = {store.last_date('us', 'AAPL')}")
    print(f"last_date(kr, 005930) = {store.last_date('kr', '005930')}")

    section("(a-4) Fallback trigger demo: bogus ticker walks the full KR chain")
    bad, bad_sources = fetch_kr_ohlcv(["999999"], start=date(2026, 1, 1))
    print(f"result rows={len(bad)}  sources={bad_sources}  (expected: empty, all 3 sources logged failures above)")

    section("(a-5) Universe loaders")
    us_uni = load_us_universe(refresh=True)
    print(f"US universe: {len(us_uni)} tickers; head: {us_uni['ticker'].head(5).tolist()}")
    kr_uni = load_kr_universe()
    print(f"KR universe: {len(kr_uni)} tickers; markets: {kr_uni['market'].value_counts().to_dict()}")

    section("(a-6) Fundamentals best-effort")
    print(fetch_fundamentals("AAPL").as_dict())
    print(fetch_fundamentals("005930", yf_symbol="005930.KS").as_dict())

    section("(e) Adjustment check: NVDA 10:1 split (2024-06-10)")
    nvda = fetch_us_ohlcv(["NVDA"], start=date(2024, 6, 2), end=date(2024, 6, 14))
    print(nvda[["date", "close", "volume", "source"]].to_string())
    pre = nvda[nvda["date"] < date(2024, 6, 10)]["close"].iloc[-1]
    post = nvda[nvda["date"] >= date(2024, 6, 10)]["close"].iloc[0]
    jump = abs(post / pre - 1) * 100
    print(f"pre-split last close={pre:.2f} post-split first close={post:.2f} jump={jump:.1f}% "
          f"(adjusted OK if ~normal daily move, NOT ~90% drop)")

    section("(e) Adjustment check: 에코프로 086520 5:1 액면분할 (2024-04)")
    win_start, win_end = date(2024, 4, 15), date(2024, 5, 3)
    fdr_df, fdr_src = fetch_kr_ohlcv(["086520"], start=win_start, end=win_end, markets={"086520": "KOSDAQ"})
    pykrx_df = _fetch_pykrx("086520", win_start, win_end)
    yf_df = _fetch_yfinance_kr("086520", win_start, win_end, "KOSDAQ")
    merged = (
        fdr_df[["date", "close"]].rename(columns={"close": f"close_{fdr_src.get('086520', 'fdr')}"})
        .merge(pykrx_df[["date", "close"]].rename(columns={"close": "close_pykrx"}), on="date")
        .merge(yf_df[["date", "close"]].rename(columns={"close": "close_yfinance"}), on="date")
    )
    print(merged.to_string())
    base = merged.iloc[:, 1]
    for col in merged.columns[2:]:
        max_dev = (merged[col] / base - 1).abs().max() * 100
        print(f"max deviation {col} vs {merged.columns[1]}: {max_dev:.2f}%")

    print("\n--- LOCAL VERIFICATION DONE ---")


if __name__ == "__main__":
    main()
