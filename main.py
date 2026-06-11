"""swing-trader CLI entry point (run from repo root).

Commands:
    scan-us / scan-kr / scan-kr-midday  — fetch, scan, report, Pages, Telegram
    gap-guard-us                        — pre-market price re-check (§11.1)
    weekly                              — tracking report, circuit breaker,
                                          universe refresh, re-validation
    backtest [--smoke]                  — Phase-4 validation gates
    analyze TICKER                      — on-demand deep analysis (Phase 6)
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta

os.environ.setdefault("TQDM_DISABLE", "1")

from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("main")

JOB_KR = {
    "scan-us": "미국 정규 스캔",
    "scan-kr": "한국 정규 스캔",
    "scan-kr-midday": "한국 예비 스캔",
    "gap-guard-us": "미국 프리마켓 갭 체크",
    "weekly": "주간 점검",
}


def _publish(publish: bool) -> None:
    """Push data branch (parquet + signals + breaker state) when on CI."""
    if not publish:
        logger.info("publish skipped (local run)")
        return
    from src.data.store import publish_to_data_branch

    publish_to_data_branch()


def _scan(market: str, preliminary: bool = False, publish: bool = True) -> None:
    """Full confirmed-scan pipeline for one market."""
    from src.analysis.registry import get_strategies
    from src.analysis.signal_engine import scan_market
    from src.backtest import tracker
    from src.backtest.confidence import ticker_confidence
    from src.data.fundamentals import fetch_fundamentals
    from src.data.store import ParquetStore
    from src.data.universe import load_kr_universe, load_us_universe
    from src.notify import messages, telegram
    from src.report.html_builder import build_report, report_url
    from src.report.publisher import publish_reports
    from src.risk import circuit_breaker
    from src.risk.positions import evaluate_position, load_positions

    from src.data.store import restore_from_data_branch

    restore_from_data_branch()  # fresh runner checkout: pull the archive first
    store = ParquetStore()
    start = date.today() - timedelta(days=365 * settings.HISTORY_YEARS)
    kr_third = False
    if market == "us":
        from src.data.us_fetcher import fetch_us_ohlcv

        universe = load_us_universe(refresh=True)
        ohlcv = fetch_us_ohlcv(universe["ticker"].tolist(), start=start)
    else:
        from src.data.kr_fetcher import fetch_kr_ohlcv, yfinance_fallback_used

        universe = load_kr_universe()
        markets = dict(zip(universe["ticker"], universe["market"]))
        ohlcv, sources = fetch_kr_ohlcv(universe["ticker"].tolist(), start=start, markets=markets)
        kr_third = yfinance_fallback_used(sources)
    if ohlcv.empty:
        raise RuntimeError(f"scan-{market}: all data sources failed — no data fetched")
    store.upsert(ohlcv, market)

    names = dict(zip(universe["ticker"], universe["name"]))
    result = scan_market(market, store.load(market), names)

    # Circuit breaker: mute suspended strategies' signals.
    cb_state = circuit_breaker.load_state()
    muted = [s for s in result.signals if circuit_breaker.is_suspended(s.strategy_id, cb_state)]
    result.signals = [s for s in result.signals if s not in muted]
    if muted:
        logger.warning("circuit breaker muted %d signals", len(muted))

    # Per-ticker confidence + reports for ranked signals (never full universe).
    strategies = {s.strategy_id: s for s in get_strategies(enabled_only=False)}
    urls: dict[str, str] = {}
    conf_labels: dict[str, str] = {}
    for sig in result.signals:
        df_ind = result.signal_frames.get(sig.ticker)
        if df_ind is None:
            continue
        strategy = strategies.get(sig.strategy_id)
        if strategy is None:  # confluence merge
            conf_labels[sig.ticker] = "콘플루언스"
            continue
        conf = ticker_confidence(df_ind, strategy, sig.ticker, market)
        conf_labels[sig.ticker] = f"{conf.score:.2f}"
        # Final rank = strength x confidence (re-rank below).
        sig.strength = round(sig.strength * max(conf.score, 0.1), 1)
        yf_symbol = sig.ticker if market == "us" else f"{sig.ticker}.KS"
        fund = fetch_fundamentals(sig.ticker, yf_symbol=yf_symbol)
        path = build_report(
            sig, df_ind, conf, fund,
            regime_label=result.regime.label_kr if result.regime else "—",
            downgraded=bool(result.regime and result.regime.weak),
        )
        urls[sig.ticker] = report_url(path)
    result.signals.sort(key=lambda s: s.strength, reverse=True)

    tracker.record_signals(result.signals)
    n_published = publish_reports() if publish else 0
    logger.info("reports published: %d", n_published)

    # Position monitoring (sell alerts + holdings one-liners; Telegram ONLY).
    from src.analysis.indicators import compute_indicators

    data = store.load(market)
    data["date"] = __import__("pandas").to_datetime(data["date"]).dt.date
    sell_msgs: list[str] = []
    holding_rows: list[dict] = []
    for pos in [p for p in load_positions() if p.market == market]:
        tdf = data[data["ticker"] == pos.ticker].sort_values("date").reset_index(drop=True)
        if tdf.empty:
            continue
        reason, summary = evaluate_position(pos, compute_indicators(tdf))
        if summary:
            summary["name"] = names.get(pos.ticker, pos.ticker)
            holding_rows.append(summary)
        if reason:
            sell_msgs.append(
                messages.sell_alert(
                    pos.ticker, names.get(pos.ticker, pos.ticker), market,
                    reason, pos.entry_price, summary["current"],
                )
            )

    _publish(publish)

    text = messages.scan_message(result, urls, conf_labels, preliminary, kr_third)
    telegram.send_message(text)
    for msg in sell_msgs:
        telegram.send_message(msg)
    if holding_rows:
        telegram.send_message(messages.holdings_summary(holding_rows))
    logger.info("scan-%s complete: %d signals, %d sell alerts", market, len(result.signals), len(sell_msgs))


def _gap_guard() -> None:
    """us-premarket job: silent when there were no US signals this morning."""
    from src.data.store import restore_from_data_branch
    from src.notify import messages, telegram
    from src.risk.gap_guard import check_us_gaps

    restore_from_data_branch()  # signals store rides the data branch
    items = check_us_gaps()
    if not items:
        logger.info("gap guard: no US signals to check — sending nothing (by design)")
        return
    telegram.send_message(messages.gap_guard_message(items))


def _weekly(publish: bool = True) -> None:
    """Weekly job: tracking report, circuit breaker, universe refresh, re-validation."""
    from src.analysis.registry import get_strategies
    from src.backtest import tracker
    from src.backtest.run_validation import run as run_validation
    from src.data.store import ParquetStore
    from src.data.universe import load_us_universe
    from src.notify import telegram
    from src.risk import circuit_breaker

    from src.data.store import restore_from_data_branch

    restore_from_data_branch()
    load_us_universe(refresh=True)  # re-validate the cached fallback list

    store = ParquetStore()
    fwd = tracker.forward_returns(store, tracker.load_signals())
    summary = tracker.weekly_summary_kr(fwd)

    strategy_ids = [s.strategy_id for s in get_strategies(enabled_only=False)]
    decisions = circuit_breaker.update_all(fwd, strategy_ids)
    cb_lines = [f"· {d.strategy_id}: {d.reason_kr}" for d in decisions if d.suspended]

    reports = run_validation()
    val_lines = [
        f"· {sid}: {'게이트 통과' if r.passed else '게이트 미달'}" for sid, r in reports.items()
    ]
    text = (
        f"{summary}\n\n🔁 주간 재검증 결과 (enabled 변경은 수동 승인 필요):\n" + "\n".join(val_lines)
    )
    if cb_lines:
        text += "\n\n🛑 서킷브레이커 발동:\n" + "\n".join(cb_lines)
    _publish(publish)
    telegram.send_message(text)


def main() -> None:
    """Parse CLI arguments and dispatch with a Telegram-alerting crash guard."""
    parser = argparse.ArgumentParser(prog="swing-trader")
    parser.add_argument("--no-publish", action="store_true", help="skip branch pushes (local runs)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scan-us", "scan-kr", "scan-kr-midday", "gap-guard-us", "weekly"):
        sub.add_parser(name)
    backtest = sub.add_parser("backtest")
    backtest.add_argument("--smoke", action="store_true")
    analyze = sub.add_parser("analyze")
    analyze.add_argument("ticker")
    args = parser.parse_args()
    publish = not args.no_publish

    try:
        if args.command == "scan-us":
            _scan("us", publish=publish)
        elif args.command == "scan-kr":
            _scan("kr", publish=publish)
        elif args.command == "scan-kr-midday":
            _scan("kr", preliminary=True, publish=publish)
        elif args.command == "gap-guard-us":
            _gap_guard()
        elif args.command == "weekly":
            _weekly(publish=publish)
        elif args.command == "backtest":
            from src.backtest.run_validation import run

            run(smoke=args.smoke)
        else:
            logger.error("command %r is wired in a later phase", args.command)
            sys.exit(2)
    except Exception as exc:  # crash guard: alert the owner, then re-raise for CI
        from src.notify import messages, telegram

        telegram.send_message(messages.format_exception(JOB_KR.get(args.command, args.command), exc))
        raise


if __name__ == "__main__":
    main()
