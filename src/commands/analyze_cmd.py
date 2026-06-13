"""/analyze {ticker}: on-demand deep analysis (spec §9).

Works for ANY ticker (auto-detect: 6-digit = KR, alphabetic = US), in or out
of the universe. Output: full report with per-strategy condition checklist,
per-strategy backtest confidence, z-score, RS percentile vs the stored
universe, regime + VIX, fundamentals, Kelly hint. Invalid ticker -> clear
Korean error reply, never silent failure.
"""

import logging
from datetime import date, timedelta

from config import settings
from src.analysis.base_strategy import Signal
from src.analysis.indicators import compute_indicators, rs_composite
from src.analysis.registry import get_strategies
from src.analysis.signal_engine import _next_earnings_within
from src.analysis.regime import get_regime
from src.backtest.confidence import ticker_confidence
from src.commands.positions_cmd import detect_market
from src.data.fundamentals import fetch_fundamentals
from src.data.store import ParquetStore
from src.notify.telegram import send_message
from src.report.html_builder import build_report, report_url
from src.report.publisher import publish_reports
from src.risk.kelly import kelly_hint_kr

logger = logging.getLogger(__name__)


def _fetch_ticker(ticker: str, market: str):
    """3y OHLCV for one ticker via the market's fetcher chain."""
    start = date.today() - timedelta(days=365 * settings.HISTORY_YEARS)
    if market == "us":
        from src.data.us_fetcher import fetch_single_us

        return fetch_single_us(ticker, start=start)
    from src.data.kr_fetcher import fetch_kr_ohlcv

    df, _ = fetch_kr_ohlcv([ticker], start=start)
    return df


def _rs_percentile_vs_universe(df_close, market: str, store: ParquetStore) -> float | None:
    """Candidate's composite momentum ranked against the stored universe."""
    import numpy as np
    import pandas as pd

    own = rs_composite(df_close)
    if np.isnan(own):
        return None
    data = store.load(market)
    if data.empty:
        return None
    scores = []
    for _, grp in data.groupby("ticker"):
        s = rs_composite(grp.sort_values("date")["close"].reset_index(drop=True))
        if not np.isnan(s):
            scores.append(s)
    if not scores:
        return None
    return float((pd.Series(scores) < own).mean() * 100)


def analyze(ticker: str, publish: bool = True) -> None:
    """Run the deep analysis and deliver report link via Telegram."""
    ticker = ticker.upper()
    market = detect_market(ticker)
    ohlcv = _fetch_ticker(ticker, market)
    if ohlcv is None or ohlcv.empty:
        send_message(
            f"❌ '{ticker}' 종목을 찾을 수 없습니다.\n"
            f"미국 주식은 티커(예: AAPL), 한국 주식은 6자리 코드(예: 005930)로 입력해주세요."
        )
        return
    df_ind = compute_indicators(ohlcv.sort_values("date").reset_index(drop=True))
    last = df_ind.iloc[-1]
    store = ParquetStore()

    # Per-strategy checklist + confidence (every strategy, enabled flag shown).
    checklist: list[str] = []
    ranking: list[dict] = []
    best_conf = None
    for strategy in get_strategies(enabled_only=False):
        suffix = "" if strategy.enabled else " (비활성)"
        if not strategy.eligible(df_ind):
            checklist.append(f"{strategy.name_kr}{suffix}: 데이터 부족 ({len(df_ind)}봉 < {strategy.min_bars}봉)")
            continue
        checklist.append(strategy.checklist_kr(df_ind) + suffix)
        conf = ticker_confidence(df_ind, strategy, ticker, market)
        ranking.append(
            {
                "name": strategy.name_kr + suffix,
                "n": conf.n_trades,
                "wr": f"{conf.win_rate * 100:.0f}%" if conf.win_rate == conf.win_rate else "—",
                "pf": f"{conf.profit_factor:.2f}" if conf.profit_factor == conf.profit_factor else "—",
                "label": conf.label_kr,
            }
        )
        if conf.n_trades > 0 and (best_conf is None or conf.score > best_conf.score):
            best_conf = conf
    ranking.sort(key=lambda r: r["n"], reverse=True)

    rs_pct = _rs_percentile_vs_universe(df_ind["close"], market, store)
    regime = get_regime(market, None)
    earnings = _next_earnings_within(ticker, market, settings.EARNINGS_WARN_DAYS)

    tags = [f"RS 모멘텀 상위 {100 - rs_pct:.0f}%"] if rs_pct is not None else ["RS 모멘텀: 유니버스 데이터 없음"]
    if earnings:
        tags.append(f"⚠️ {earnings:%m/%d} 실적발표 예정 — 갭 리스크")

    pseudo = Signal(
        ticker=ticker, name=ticker, market=market, strategy_id="딥 분석",
        direction="BUY", strength=0.0, price=float(last["close"]),
        signal_date=last["date"], indicators={}, suggested_stop_loss=None,
        suggested_take_profit=None, exit_mode="fixed",
        reason="온디맨드 딥 분석 — 매수 신호가 아닌 현재 상태 진단입니다.", tags=tags,
    )
    # Wyckoff badge: scan path sets this (main.py); analyze must mirror it so the
    # report header reflects the real stage count instead of the "" fallback.
    from src.analysis.base_strategy import load_strategy_config
    from src.analysis.wyckoff_vpa import diagnose_stage_count, wyckoff_badge_kr

    vpa_params = load_strategy_config()["strategies"]["wyckoff_spring"]["params"]["vpa"]
    pseudo.wyckoff_badge = wyckoff_badge_kr(diagnose_stage_count(df_ind, vpa_params))

    # Entry band + ATR reference stop: scan path computes these (main.py), so the
    # report shows a real 추격 금지선 and a chandelier-style 참고 손절 instead of
    # collapsing the 매수 범위 onto the current price. /analyze fires no strategy,
    # so the stop is informational (ANALYZE_REF_ATR_K), never a live level.
    from src.analysis.grading import entry_zone_top
    from src.risk.exit_engine import atr_trailing_stop

    last_atr = last["atr14"]
    atr = float(last_atr) if last_atr == last_atr and last_atr > 0 else None
    pseudo.entry_zone_top = entry_zone_top(pseudo.price, atr)
    if atr is not None:
        pseudo.suggested_stop_loss = round(
            atr_trailing_stop(pseudo.price, atr, settings.ANALYZE_REF_ATR_K), 4
        )
        pseudo.exit_mode = "atr_reference"
    from src.backtest.confidence import ConfidenceReport

    conf_for_report = best_conf or ConfidenceReport(
        ticker=ticker, strategy_id="—", n_trades=0, win_rate=float("nan"),
        profit_factor=float("nan"), avg_holding_days=float("nan"),
        max_drawdown_pct=float("nan"), score=0.0, label_kr="과거 시그널 없음",
    )
    if market == "us":
        fund = fetch_fundamentals(ticker)
    else:  # exchange unknown for arbitrary KR codes: try KOSPI, then KOSDAQ
        fund = fetch_fundamentals(ticker, yf_symbol=f"{ticker}.KS")
        if fund.market_cap is None and fund.week52_high is None:
            fund = fetch_fundamentals(ticker, yf_symbol=f"{ticker}.KQ")
    path = build_report(
        pseudo, df_ind, conf_for_report, fund,
        regime_label=regime.label_kr, downgraded=False,
        strategy_ranking=ranking, kelly_hint=kelly_hint_kr(conf_for_report),
        checklist=checklist,
    )
    if publish:
        publish_reports()
    z = last["zscore20"]
    z_txt = f"{z:+.1f}σ" if z == z else "—"
    send_message(
        f"🔍 {ticker} 딥 분석 완료\n"
        f"현재가 기준 z-score {z_txt} · {regime.label_kr}\n"
        f"📄 {report_url(path)}"
    )
    logger.info("analyze %s done: %s", ticker, path.name)
