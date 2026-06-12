"""Jinja2 HTML report builder (spec §10).

Filenames are non-guessable ({date}-{ticker}-{8-hex}.html), there is no index
page, and reports NEVER contain the owner's positions/entries/quantities.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import settings
from src.analysis.base_strategy import Signal
from src.analysis.summarize_kr import summarize_kr
from src.backtest.confidence import ConfidenceReport
from src.data.fundamentals import Fundamentals
from src.report.plotly_chart import build_chart_html

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
TEMPLATES_DIR = Path(__file__).parent / "templates"
REPORTS_OUT_DIR = settings.REPO_ROOT / "reports_out"  # gitignored; published to gh-pages

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)

MARKET_LABEL = {"us": "미국", "kr": "한국"}


def _fmt_price(value: float | None, market: str) -> str:
    if value is None or value != value:
        return "—"
    return f"{value:,.0f}원" if market == "kr" else f"${value:,.2f}"


def _own_52w(df_ind: pd.DataFrame) -> tuple[float, float]:
    """52-week high/low from OUR adjusted series (last 252 trading days).

    A-1 defense: yfinance .info served stale quotes for KOSDAQ tickers
    (131290 case: 52w high 90,500 vs actual 282,500) — the position gauge is
    therefore ALWAYS computed from our own data, never external fields.
    """
    recent = df_ind.tail(252)
    return float(recent["high"].max()), float(recent["low"].min())


def _fundamentals_rows(
    fund: Fundamentals, market: str, last_close: float, df_ind: pd.DataFrame
) -> list[tuple[str, str]]:
    def num(v: float | None, fmt: str = "{:,.1f}") -> str:
        return "정보 없음" if v is None else fmt.format(v)

    cap = fund.market_cap
    if cap is None:
        cap_s = "정보 없음"
    elif market == "kr":
        cap_s = f"{cap / 1e12:,.1f}조원"
    else:
        cap_s = f"${cap / 1e9:,.1f}B"

    own_high, own_low = _own_52w(df_ind)
    pos = (last_close - own_low) / (own_high - own_low) * 100 if own_high > own_low else float("nan")
    rows = [
        ("PER", num(fund.per)),
        ("PBR", num(fund.pbr)),
        ("시가총액", cap_s),
        ("배당수익률", "정보 없음" if fund.dividend_yield is None else f"{fund.dividend_yield:.2f}%"),
    ]
    if pos == pos:
        rows.append(("52주 고저 대비 (자체 시세)", f"{pos:.0f}% 위치"))
    # External 52w shown ONLY when consistent with our own series (±5%).
    tol = settings.FUND_52W_DEVIATION_MAX_PCT / 100.0
    if (
        fund.week52_high and fund.week52_low
        and abs(fund.week52_high / own_high - 1) <= tol
        and abs(fund.week52_low / own_low - 1) <= tol
    ):
        rows.append(
            ("52주 최고/최저", f"{_fmt_price(fund.week52_high, market)} / {_fmt_price(fund.week52_low, market)}")
        )
    elif fund.week52_high or fund.week52_low:
        logger.warning(
            "fundamentals 52w deviates >%s%% from own data (%s vs own %.0f/%.0f) — hidden",
            settings.FUND_52W_DEVIATION_MAX_PCT, fund.ticker, own_high, own_low,
        )
    return rows


def _overfit_label(conf: ConfidenceReport) -> str:
    if conf.n_trades < settings.CONF_MIN_TRADES:
        return "표본부족"
    return "낮음" if conf.score >= 0.6 else "주의"


def build_report(
    signal: Signal,
    df_ind: pd.DataFrame,
    confidence: ConfidenceReport,
    fundamentals: Fundamentals,
    regime_label: str,
    downgraded: bool,
    strategy_ranking: list[dict] | None = None,
    kelly_hint: str | None = None,  # None = row not rendered (A-5: low sample)
    correlation_warning: str | None = None,
    checklist: list[str] | None = None,
) -> Path:
    """Render one signal's HTML report to REPORTS_OUT_DIR.

    Returns:
        Path of the written file (random-hash name).
    """
    import json

    from src.report.lw_chart import (
        _weekly_frame,
        prepare_chart_payload,
        vpa_diagnosis,
        weekly_lines_kr,
    )

    market = signal.market
    last = df_ind.iloc[-1]
    chart = chart_payload = None
    if settings.CHART_BACKEND == "lightweight":
        try:
            chart_payload = json.dumps(prepare_chart_payload(df_ind, signal), ensure_ascii=False)
        except Exception:
            logger.exception("lightweight chart payload failed — falling back to plotly")
    if chart_payload is None:  # plotly fallback (rollback path, retained by spec)
        chart = build_chart_html(
            df_ind, markers=[{"date": signal.signal_date, "kind": "BUY", "price": signal.price}]
        )
    daily = df_ind[["date", "open", "high", "low", "close", "volume"]]
    weekly = _weekly_frame(daily)
    diagnosis = vpa_diagnosis(daily, weekly)
    weekly_lines = weekly_lines_kr(weekly)
    target = (
        _fmt_price(signal.suggested_take_profit, market)
        if signal.suggested_take_profit
        else ("ATR 추적 청산" if signal.exit_mode == "atr_trailing" else "전략 조건 청산")
    )
    zone = (
        f"{_fmt_price(signal.price, market)} ~ {_fmt_price(signal.entry_zone_top, market)}"
        if signal.entry_zone_top
        else _fmt_price(signal.price, market)
    )
    template = _env.get_template("report.html.j2")
    html = template.render(
        name=signal.name,
        ticker=signal.ticker,
        market_label=MARKET_LABEL[market],
        issued_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        grade=signal.grade,
        grade_basis=signal.grade_basis,
        wyckoff_badge=signal.wyckoff_badge,
        contrarian=signal.contrarian,
        strategy_badges=[signal.strategy_id],
        strength=f"{signal.strength:.0f}",
        confidence_label=f"{confidence.score:.2f}",
        tags=signal.tags,
        chart_html=chart,
        chart_payload=chart_payload,
        lw_cdn=settings.LW_CHARTS_CDN,
        vpa={"stages": diagnosis["stages"], "weekly_context": diagnosis["weekly_context"]},
        weekly_lines=weekly_lines,
        indicator_lines=summarize_kr(last, market),
        checklist=checklist or [],
        fundamentals=_fundamentals_rows(fundamentals, market, float(last["close"]), df_ind),
        reason=signal.reason,
        strategy_ranking=strategy_ranking or [],
        plan={
            "entry": zone,
            "stop": _fmt_price(signal.suggested_stop_loss, market),
            "stop_mode": "ATR 추적" if signal.exit_mode == "atr_trailing" else "고정",
            "target": target,
            "kelly": kelly_hint,
            "correlation_warning": correlation_warning,
        },
        confidence={
            "n": confidence.n_trades,
            "wr": f"{confidence.win_rate * 100:.0f}%" if confidence.win_rate == confidence.win_rate else "—",
            "pf": f"{confidence.profit_factor:.2f}" if confidence.profit_factor == confidence.profit_factor else "—",
            "mdd": f"{confidence.max_drawdown_pct:.1f}%" if confidence.max_drawdown_pct == confidence.max_drawdown_pct else "—",
            "risk_label": _overfit_label(confidence),
            "low_sample": confidence.low_sample,
            "label": confidence.label_kr,
        },
        validation_note="IS/OoS·몬테카를로 상세는 주간 검증 리포트 기준입니다.",
        regime_label=regime_label,
        downgraded=downgraded,
    )
    REPORTS_OUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{signal.signal_date}-{signal.ticker}-{secrets.token_hex(4)}.html"
    path = REPORTS_OUT_DIR / fname
    path.write_text(html, encoding="utf-8")
    logger.info("report written: %s", fname)
    return path


def report_url(path: Path) -> str:
    """Public Pages URL for a generated report file."""
    return f"{settings.PAGES_BASE_URL}/{path.name}"
