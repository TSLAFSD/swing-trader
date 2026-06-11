"""Phase 2 runner feasibility test — runs ON the GitHub Actions runner.

Proves data reachability from GitHub's overseas (Azure) IPs:
  - US via yfinance (must pass)
  - KR via each source independently: FDR, pykrx, yfinance .KS
  - Intraday freshness: does FDR/pykrx serve TODAY's (in-progress) bar?
    (meaningful when triggered by the 12:30 KST cron)

Never raises on KR failures — reports them; US failure exits non-zero.
"""

import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("runner-verify")

KST = timezone(timedelta(hours=9))


def main() -> None:  # noqa: D103
    now_kst = datetime.now(KST)
    today_kst = now_kst.date()
    print(f"=== runner test @ {now_kst:%Y-%m-%d %H:%M} KST ===")
    start = today_kst - timedelta(days=30)
    us_ok = False

    print("\n--- US: AAPL via yfinance (MUST PASS) ---")
    try:
        from src.data.us_fetcher import fetch_us_ohlcv

        us = fetch_us_ohlcv(["AAPL"], start=start)
        assert not us.empty, "empty result"
        print(us.tail(3).to_string())
        print(f"US OK: {len(us)} rows, last bar {us['date'].max()}")
        us_ok = True
    except Exception:
        logger.exception("US fetch FAILED on runner")

    print("\n--- KR source 1: FDR (005930) ---")
    fdr_last = None
    try:
        from src.data.kr_fetcher import _fetch_fdr

        df = _fetch_fdr("005930", start, today_kst)
        fdr_last = df["date"].max()
        print(df.tail(3).to_string())
        print(f"FDR OK: {len(df)} rows, last bar {fdr_last}")
    except Exception:
        logger.exception("FDR FAILED on runner")

    print("\n--- KR source 2: pykrx (005930) ---")
    pykrx_last = None
    try:
        from src.data.kr_fetcher import _fetch_pykrx

        df = _fetch_pykrx("005930", start, today_kst)
        pykrx_last = df["date"].max()
        print(df.tail(3).to_string())
        print(f"pykrx OK: {len(df)} rows, last bar {pykrx_last}")
    except Exception:
        logger.exception("pykrx FAILED on runner")

    print("\n--- KR source 3: yfinance 005930.KS ---")
    try:
        from src.data.kr_fetcher import _fetch_yfinance_kr

        df = _fetch_yfinance_kr("005930", start, today_kst, "KOSPI")
        print(df.tail(3).to_string())
        print(f"yfinance KR OK: {len(df)} rows, last bar {df['date'].max()}")
    except Exception:
        logger.exception("yfinance KR FAILED on runner")

    print("\n--- (d) Intraday freshness verdict ---")
    market_hours = now_kst.weekday() < 5 and 9 <= now_kst.hour < 15 or (now_kst.hour == 15 and now_kst.minute < 30)
    for name, last in [("FDR", fdr_last), ("pykrx", pykrx_last)]:
        if last is None:
            print(f"{name}: source unreachable — no verdict")
        elif last == today_kst:
            qualifier = "IN-PROGRESS bar (intraday OK)" if market_hours else "today's bar (after close — EOD latency OK)"
            print(f"{name}: serves {qualifier}: {last}")
        else:
            print(f"{name}: last bar {last} — does NOT serve today's bar at this time")

    if not us_ok:
        print("\nFATAL: US pipeline failed on runner")
        sys.exit(1)
    print("\n--- RUNNER TEST DONE (US OK) ---")


if __name__ == "__main__":
    main()
