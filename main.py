"""swing-trader CLI entry point.

Usage (run from repo root):
    python main.py scan-us            # US confirmed scan
    python main.py scan-kr            # KR confirmed scan
    python main.py scan-kr-midday     # KR preliminary scan (예비/미확정 tag)
    python main.py weekly             # weekly maintenance job        (Phase 4+)
    python main.py backtest           # strategy validation gates     (Phase 4)
    python main.py analyze TICKER     # on-demand deep analysis       (Phase 6)

Phase 3 wires the scan commands up to the signal engine; reporting/Telegram
delivery is attached in Phase 5.
"""

import argparse
import logging
import sys
from datetime import date, timedelta

from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("main")


def _scan(market: str, preliminary: bool = False) -> None:
    """Fetch latest data for the market universe, store it, run the engine."""
    from src.analysis.signal_engine import scan_market
    from src.data.store import ParquetStore
    from src.data.universe import load_kr_universe, load_us_universe

    store = ParquetStore()
    start = date.today() - timedelta(days=365 * settings.HISTORY_YEARS)
    if market == "us":
        from src.data.us_fetcher import fetch_us_ohlcv

        universe = load_us_universe(refresh=True)
        ohlcv = fetch_us_ohlcv(universe["ticker"].tolist(), start=start)
    else:
        from src.data.kr_fetcher import fetch_kr_ohlcv, yfinance_fallback_used

        universe = load_kr_universe()
        markets = dict(zip(universe["ticker"], universe["market"]))
        ohlcv, sources = fetch_kr_ohlcv(universe["ticker"].tolist(), start=start, markets=markets)
        if yfinance_fallback_used(sources):
            logger.warning("3rd source (yfinance) served some KR tickers — accuracy caveat applies")
    if ohlcv.empty:
        logger.error("scan-%s: fetch produced no data — aborting", market)
        sys.exit(1)
    store.upsert(ohlcv, market)

    names = dict(zip(universe["ticker"], universe["name"]))
    result = scan_market(market, store.load(market), names)
    tag = " [예비(미확정)]" if preliminary else ""
    logger.info(
        "scan-%s%s: %d scanned, %d signals, breadth %.1f%%",
        market, tag, result.total_scanned, len(result.signals),
        result.breadth_pct if result.breadth_pct == result.breadth_pct else float("nan"),
    )
    for sig in result.signals:
        logger.info("  %s %s strength=%.0f price=%.2f %s", sig.strategy_id, sig.ticker, sig.strength, sig.price, sig.reason)
    # Phase 5: reports + Pages + Telegram delivery attach here.


def main() -> None:
    """Parse CLI arguments and dispatch."""
    parser = argparse.ArgumentParser(prog="swing-trader")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan-us")
    sub.add_parser("scan-kr")
    sub.add_parser("scan-kr-midday")
    sub.add_parser("weekly")
    backtest = sub.add_parser("backtest")
    backtest.add_argument("--smoke", action="store_true", help="tiny debug sample (never gates YAML)")
    analyze = sub.add_parser("analyze")
    analyze.add_argument("ticker")
    args = parser.parse_args()

    if args.command == "scan-us":
        _scan("us")
    elif args.command == "scan-kr":
        _scan("kr")
    elif args.command == "scan-kr-midday":
        _scan("kr", preliminary=True)
    elif args.command == "backtest":
        from src.backtest.run_validation import run

        run(smoke=args.smoke)
    else:
        logger.error("command %r is wired in a later phase", args.command)
        sys.exit(2)


if __name__ == "__main__":
    main()
