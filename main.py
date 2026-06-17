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
    "feedback": "페이퍼 트레이딩 분석",
    "analyze": "종목 딥 분석",
    "position-add": "보유 종목 추가",
    "position-remove": "보유 종목 제거",
    "positions-report": "보유 현황 조회",
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
    from src.analysis.base_strategy import load_strategy_config
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
    kr_markets: dict[str, str] = {}  # ticker -> KOSPI | KOSDAQ (yfinance suffix)
    if market == "us":
        from src.data.us_fetcher import fetch_us_ohlcv

        universe = load_us_universe(refresh=True)
        ohlcv = fetch_us_ohlcv(universe["ticker"].tolist(), start=start)
    else:
        from src.data.kr_fetcher import fetch_kr_ohlcv, yfinance_fallback_used

        universe = load_kr_universe()
        kr_markets = dict(zip(universe["ticker"], universe["market"]))
        ohlcv, sources = fetch_kr_ohlcv(universe["ticker"].tolist(), start=start, markets=kr_markets)
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

    # Rebuy cooldown: drop fresh signals for recently removed tickers.
    from src.commands.positions_cmd import cooldown_blocked

    blocked = cooldown_blocked([s.ticker for s in result.signals])
    if blocked:
        logger.info("rebuy cooldown dropped: %s", sorted(blocked))
        result.signals = [s for s in result.signals if s.ticker not in blocked]

    # Per-ticker confidence + reports for ranked signals (never full universe).
    from src.risk.correlation import correlation_warning
    from src.risk.kelly import kelly_hint_kr

    held = [p.ticker for p in load_positions() if p.market == market]
    held_data = store.load(market, tickers=held) if held else None
    strategies = {s.strategy_id: s for s in get_strategies(enabled_only=False)}
    urls: dict[str, str] = {}
    conf_labels: dict[str, str] = {}
    confs: dict[str, object] = {}  # ticker -> ConfidenceReport (send filter)
    for sig in result.signals:
        df_ind = result.signal_frames.get(sig.ticker)
        if df_ind is None:
            continue
        strategy = strategies.get(sig.strategy_id)
        if strategy is None:
            logger.warning("no strategy instance for %s — skipping", sig.strategy_id)
            continue
        conf = ticker_confidence(df_ind, strategy, sig.ticker, market)
        confs[sig.ticker] = conf
        conf_labels[sig.ticker] = f"{conf.score:.2f}"
        # Final rank = strength x confidence (re-rank below).
        sig.strength = round(sig.strength * max(conf.score, 0.1), 1)

        # U4 enrichments: grade / Wyckoff badge / entry zone / contrarian list.
        from src.analysis.grading import composite_grade, contrarian_indicators, entry_zone_top
        from src.analysis.wyckoff_vpa import diagnose_stage_count, wyckoff_badge_kr

        grade = composite_grade(
            sig.strength, conf.score,
            result.regime.downgrade_factor if result.regime else None,
        )
        sig.grade, sig.grade_value, sig.grade_basis = grade.letter, grade.value, grade.basis_kr
        sig.confidence = conf.score
        sig.regime_factor = result.regime.downgrade_factor if result.regime else None
        vpa_params = load_strategy_config()["strategies"]["wyckoff_spring"]["params"]["vpa"]
        sig.wyckoff_badge = wyckoff_badge_kr(diagnose_stage_count(df_ind, vpa_params))
        last_atr = df_ind["atr14"].iloc[-1]
        sig.entry_zone_top = entry_zone_top(sig.price, None if last_atr != last_atr else float(last_atr))
        sig.contrarian = contrarian_indicators(df_ind)
        corr_warn = None
        if held and held_data is not None and not held_data.empty:
            closes = {sig.ticker: df_ind["close"]}
            for t, grp in held_data.groupby("ticker"):
                closes[t] = grp.sort_values("date")["close"].reset_index(drop=True)
            corr_warn = correlation_warning(sig.ticker, closes, held, names)
            if corr_warn:
                sig.tags.append(corr_warn)
        if market == "us":
            yf_symbol = sig.ticker
        else:  # KOSPI -> .KS, KOSDAQ -> .KQ
            suffix = ".KQ" if kr_markets.get(sig.ticker) == "KOSDAQ" else ".KS"
            yf_symbol = f"{sig.ticker}{suffix}"
        fund = fetch_fundamentals(sig.ticker, yf_symbol=yf_symbol, market=market)
        path = build_report(
            sig, df_ind, conf, fund,
            regime_label=result.regime.label_kr if result.regime else "—",
            downgraded=bool(result.regime and result.regime.weak),
            kelly_hint=kelly_hint_kr(conf) if conf.n_trades >= settings.MIN_SAMPLE_SEND else None,
            correlation_warning=corr_warn,
        )
        urls[sig.ticker] = report_url(path)
    result.signals.sort(key=lambda s: s.strength, reverse=True)

    tracker.record_signals(result.signals)  # ALL ranked signals (weekly tracking)

    # Send-stage cutoffs (A-2): reports above were already generated for all.
    from src.notify.send_filter import filter_for_send

    sendable, send_excluded = filter_for_send(result.signals, confs)
    result.signals = sendable

    # Position monitoring (sell alerts + holdings one-liners; Telegram ONLY).
    from src.analysis.indicators import compute_indicators

    data = store.load(market)
    data["date"] = __import__("pandas").to_datetime(data["date"]).dt.date
    sell_msgs: list[str] = []
    holding_rows: list[dict] = []
    from src.risk.distribution import check_distribution
    from src.risk.positions import save_positions, update_trailing_state

    all_positions = load_positions()
    market_positions = [p for p in all_positions if p.market == market]
    position_frames: dict[str, object] = {}
    for pos in market_positions:
        tdf = data[data["ticker"] == pos.ticker].sort_values("date").reset_index(drop=True)
        if tdf.empty:
            continue
        tdf = compute_indicators(tdf)
        position_frames[pos.ticker] = tdf
        reason, summary = evaluate_position(pos, tdf)
        if summary:
            summary["name"] = names.get(pos.ticker, pos.ticker)
            # Holdings auto-report (CONFIRMED close only): the same /analyze
            # report for this ticker — NO position data in it — reusing the
            # already-computed indicator frame; US holdings also get news.
            if not preliminary and settings.HOLDINGS_REPORT_ENABLED:
                from src.commands.analyze_cmd import build_analysis_report

                try:
                    rpt = build_analysis_report(pos.ticker, market, tdf, store=store, publish=False)
                    summary["report_url"] = report_url(rpt)
                except Exception:
                    logger.exception("holdings report failed for %s", pos.ticker)
                if settings.HOLDINGS_NEWS_ENABLED and market == "us":
                    from src.data.news import fetch_us_news

                    summary["news"] = fetch_us_news(
                        pos.ticker, settings.HOLDINGS_NEWS_MAX_ITEMS, settings.HOLDINGS_NEWS_RECENCY_DAYS
                    )
            holding_rows.append(summary)
        if reason:
            sell_msgs.append(
                messages.sell_alert(
                    pos.ticker, names.get(pos.ticker, pos.ticker), market,
                    reason, pos.entry_price, summary["current"],
                )
            )
        # Distribution monitor (U3/C-2): sell-side VPA warning, never auto-sell.
        dist_warn = check_distribution(tdf, names.get(pos.ticker, pos.ticker), pos.ticker)
        if dist_warn:
            sell_msgs.append(dist_warn)

    # U7/G-1: persist ATR-trailing state — CONFIRMED scans only (preliminary
    # scans may carry in-progress bars). Saved only when values changed;
    # the workflow commits positions.yaml only on a real diff.
    if not preliminary and update_trailing_state(market_positions, position_frames):
        save_positions(all_positions)
        logger.info("positions.yaml trailing state updated")

    # Paper portfolio (가상 매매): CONFIRMED scans only — virtually buy fresh
    # A-grade signals at the confirmed close and manage them via the SAME exit
    # path as the live monitor (forward OOS track record). Runs before _publish
    # so paper/trades.parquet + paper/open.json ride the data branch. Note
    # result.signals here is already send-filtered (the actually-alerted set).
    if not preliminary and settings.PAPER_ENABLED:
        from src.paper.portfolio import update_paper_portfolio

        paper = update_paper_portfolio(market, result.signals, store)
        logger.info(
            "paper portfolio: +%d open, -%d closed, %d held",
            paper["n_opened"], len(paper["closed"]), paper["open_total"],
        )

    _publish(publish)

    # U7/G-2: slot accounting (capital-level, across both markets).
    used_slots = len(all_positions)
    if used_slots >= settings.MAX_POSITION_SLOTS:
        for sig in result.signals:
            sig.tags.append(f"⚠️ 슬롯 가득 ({used_slots}/{settings.MAX_POSITION_SLOTS})")

    # Single publish AFTER holdings reports are generated (signals + holdings),
    # so every report link below is live before the Telegram message is sent.
    n_published = publish_reports() if publish else 0
    logger.info("reports published: %d (signals + holdings)", n_published)

    text = messages.scan_message(
        result, urls, conf_labels, preliminary, kr_third, filtered_count=len(send_excluded)
    )
    telegram.send_message(text)
    for msg in sell_msgs:
        telegram.send_message(msg)
    if holding_rows:
        telegram.send_message(
            messages.holdings_summary(
                holding_rows, used_slots=used_slots,
                max_slots=settings.MAX_POSITION_SLOTS, n_signals=len(result.signals),
            )
        )
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


def _paper_benchmark_pct(trades, open_rows) -> float | None:
    """S&P500 (^GSPC) buy-and-hold return over the paper portfolio's active
    window — the 'did we beat the market' yardstick for the weekly summary."""
    import pandas as pd

    from src.paper.stats import summarize

    s = summarize(trades, open_rows)
    if not (s["period_start"] and s["period_end"]):
        return None
    try:
        from src.analysis.regime import _fetch_index_series

        series = _fetch_index_series("us")
        if series is None or len(series) == 0:
            return None
        series = series.copy()
        series.index = pd.to_datetime(series.index)
        start_slice = series[series.index <= pd.Timestamp(s["period_start"])]
        end_slice = series[series.index <= pd.Timestamp(s["period_end"])]
        if start_slice.empty or end_slice.empty:
            return None
        return float(end_slice.iloc[-1] / start_slice.iloc[-1] - 1) * 100
    except Exception:
        logger.exception("weekly: benchmark computation failed")
        return None


def _weekly(publish: bool = True) -> None:
    """Weekly job: tracking report, circuit breaker, universe refresh, re-validation."""
    from src.analysis.registry import get_strategies
    from src.backtest import tracker
    from src.backtest.run_validation import run as run_validation
    from src.data.store import ParquetStore
    from src.data.universe import load_kr_universe, load_us_universe
    from src.notify import telegram
    from src.risk import circuit_breaker

    from src.data.store import restore_from_data_branch

    restore_from_data_branch()
    load_us_universe(refresh=True)  # re-validate the cached fallback list
    load_kr_universe(refresh=True)  # ditto for KR (refreshes config/cache/kr_universe.csv)

    from src.risk.trade_ledger import discipline_summary_kr, load_closed_trades

    store = ParquetStore()
    fwd = tracker.forward_returns(store, tracker.load_signals())
    summary = tracker.weekly_summary_kr(fwd)
    realized = discipline_summary_kr(load_closed_trades())

    # Paper portfolio (P-B): forward OOS performance summary + dashboard page.
    from src.paper import portfolio as paper
    from src.paper import stats as paper_stats
    from src.report.html_builder import report_url
    from src.report.paper_report import build_paper_report

    paper_trades = paper.load_trades()
    paper_open = paper.load_open()
    benchmark = _paper_benchmark_pct(paper_trades, paper_open)
    paper_path = build_paper_report(paper_trades, paper_open, benchmark_pct=benchmark)
    paper_summary = paper_stats.summary_kr(
        paper_trades, paper_open, benchmark_pct=benchmark, url=report_url(paper_path)
    )

    # P-C feedback: reuse the already-computed forward returns (no extra compute).
    from src.paper import feedback as paper_fb

    fb_report = paper_fb.build_feedback(fwd, paper_trades)
    paper_fb.write_findings(fb_report)  # data/paper/feedback.json (rides data branch)
    insight = paper_fb.feedback_kr(fb_report, full=False)

    if publish:
        from src.report.publisher import publish_reports

        publish_reports()  # push paper.html (merges with existing per-signal reports)

    strategy_ids = [s.strategy_id for s in get_strategies(enabled_only=False)]
    enabled_ids = {s.strategy_id for s in get_strategies(enabled_only=True)}
    decisions = circuit_breaker.update_all(fwd, strategy_ids, enabled_ids=enabled_ids)
    cb_lines = []
    for d in decisions:
        if d.action == "suspended":
            cb_lines.append(f"🛑 {d.strategy_id} 중단: {d.reason_kr}")
        elif d.action == "reactivated":
            cb_lines.append(f"🟢 {d.strategy_id} 재가동: {d.reason_kr}")
        elif d.action == "safeguard_kept":
            cb_lines.append(f"⚠️ {d.strategy_id} 유지(안전장치): {d.reason_kr}")
        elif d.suspended:
            cb_lines.append(f"· {d.strategy_id} 중단 중: {d.reason_kr}")

    # Lever 3: adaptive acceptance cutoff (reuses fwd; persisted + audited).
    from src.adaptive import audit as adaptive_audit
    from src.adaptive.cutoff import propose_and_apply

    cutoff_change = propose_and_apply(fwd)
    cutoff_line = ""
    if cutoff_change and cutoff_change["changed"]:
        adaptive_audit.record(
            "acceptance_cutoff", cutoff_change["old"], cutoff_change["new"], cutoff_change["reason_kr"]
        )
        cutoff_line = (
            f"\n\n📏 수용 컷오프 {cutoff_change['old']:.0f}→{cutoff_change['new']:.0f}: "
            f"{cutoff_change['reason_kr']}"
        )

    reports = run_validation()
    val_lines = [
        f"· {sid}: {'게이트 통과' if r.passed else '게이트 미달'}" for sid, r in reports.items()
    ]
    text = (
        f"{summary}\n\n{realized}\n\n{paper_summary}\n\n{insight}\n\n"
        "🔁 주간 재검증 결과 (enabled 변경은 수동 승인 필요):\n"
        + "\n".join(val_lines)
    )
    if cb_lines:
        header = "🔁 서킷브레이커(적응형)" if settings.ADAPTIVE_LOOP_ENABLED else "🛑 서킷브레이커 발동"
        text += f"\n\n{header}:\n" + "\n".join(cb_lines)
        if settings.ADAPTIVE_LOOP_ENABLED:
            text += "\n※ 과거 실현 통계 기반 억제일 뿐 — 미래 수익을 보장하지 않습니다."
    text += cutoff_line
    _publish(publish)
    telegram.send_message(text)


def _feedback(publish: bool = True) -> None:
    """On-demand 'what worked' analysis from the paper datasets (read-only).

    Reads signals.parquet (+ forward returns) and paper/trades.parquet, writes
    machine-readable findings.json, and sends the Korean report. Suggestions are
    manual-apply only — this never changes enabled/params.
    """
    from src.backtest import tracker
    from src.data.store import ParquetStore, restore_from_data_branch
    from src.notify import telegram
    from src.paper import feedback as fb
    from src.paper import portfolio as paper

    restore_from_data_branch()
    store = ParquetStore()
    fwd = tracker.forward_returns(store, tracker.load_signals())
    report = fb.build_feedback(fwd, paper.load_trades())
    fb.write_findings(report)
    if publish:
        try:
            _publish(True)  # persist feedback.json on the data branch
        except FileNotFoundError:
            logger.info("feedback: no market parquet yet — skipping data-branch publish")
    telegram.send_message(fb.feedback_kr(report, full=True))


def main() -> None:
    """Parse CLI arguments and dispatch with a Telegram-alerting crash guard."""
    parser = argparse.ArgumentParser(prog="swing-trader")
    parser.add_argument("--no-publish", action="store_true", help="skip branch pushes (local runs)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scan-us", "scan-kr", "scan-kr-midday", "gap-guard-us", "weekly", "feedback"):
        sub.add_parser(name)
    backtest = sub.add_parser("backtest")
    backtest.add_argument("--smoke", action="store_true")
    analyze = sub.add_parser("analyze")
    analyze.add_argument("ticker")
    add = sub.add_parser("position-add")
    add.add_argument("ticker")
    add.add_argument("price", type=float)
    add.add_argument("quantity", type=float)
    remove = sub.add_parser("position-remove")
    remove.add_argument("ticker")
    remove.add_argument("price", nargs="?", type=float, default=None)
    sub.add_parser("positions-report")
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
        elif args.command == "feedback":
            _feedback(publish=publish)
        elif args.command == "backtest":
            from src.backtest.run_validation import run

            run(smoke=args.smoke)
        elif args.command == "analyze":
            from src.commands.analyze_cmd import analyze
            from src.data.store import restore_from_data_branch

            restore_from_data_branch()  # RS percentile needs the stored universe
            analyze(args.ticker, publish=publish)
        elif args.command == "position-add":
            from src.commands.positions_cmd import add_position

            add_position(args.ticker, args.price, args.quantity)
        elif args.command == "position-remove":
            from src.commands.positions_cmd import remove_position
            from src.data.store import restore_from_data_branch

            restore_from_data_branch()  # rebuy state + trade ledger ride the data branch
            remove_position(args.ticker, args.price)
            if publish:
                _publish(True)  # persist the cooldown record
        elif args.command == "positions-report":
            from src.commands.positions_cmd import positions_report
            from src.data.store import restore_from_data_branch

            restore_from_data_branch()
            positions_report()
        else:
            logger.error("unknown command %r", args.command)
            sys.exit(2)
    except Exception as exc:  # crash guard: alert the owner, then re-raise for CI
        from src.notify import messages, telegram

        telegram.send_message(messages.format_exception(JOB_KR.get(args.command, args.command), exc))
        raise


if __name__ == "__main__":
    main()
