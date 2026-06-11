"""Phase 5 verification: real report from stored data + message format demo.

Runs the scanner on stored US data (breakout now enabled), generates the HTML
report for the top signal (confidence + fundamentals + chart), and prints the
exact Telegram scan message. No network sends here.
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("TQDM_DISABLE", "1")

from src.analysis.registry import get_strategies
from src.analysis.signal_engine import scan_market
from src.backtest.confidence import ticker_confidence
from src.data.fundamentals import fetch_fundamentals
from src.data.store import ParquetStore
from src.data.universe import load_us_universe
from src.notify.messages import scan_message
from src.report.html_builder import build_report, report_url

logging.basicConfig(level=logging.WARNING)


def main() -> None:  # noqa: D103
    store = ParquetStore()
    uni = load_us_universe(refresh=False)
    names = dict(zip(uni["ticker"], uni["name"]))
    result = scan_market("us", store.load("us"), names)  # enabled_only=True: breakout
    print(f"scan: {result.total_scanned} tickers, {len(result.signals)} ENABLED-strategy signals")

    urls: dict[str, str] = {}
    conf_labels: dict[str, str] = {}
    strategies = {s.strategy_id: s for s in get_strategies(enabled_only=False)}
    for sig in result.signals:
        df_ind = result.signal_frames.get(sig.ticker)
        strategy = strategies.get(sig.strategy_id)
        if df_ind is None or strategy is None:
            continue
        conf = ticker_confidence(df_ind, strategy, sig.ticker, "us")
        conf_labels[sig.ticker] = f"{conf.score:.2f}"
        fund = fetch_fundamentals(sig.ticker)
        path = build_report(
            sig, df_ind, conf, fund,
            regime_label=result.regime.label_kr if result.regime else "—",
            downgraded=bool(result.regime and result.regime.weak),
        )
        urls[sig.ticker] = report_url(path)
        print(f"report: {path} ({path.stat().st_size / 1024:.0f} KB)")

    print("\n----- TELEGRAM MESSAGE (verbatim) -----")
    print(scan_message(result, urls, conf_labels))
    print("----- END -----")


if __name__ == "__main__":
    main()
