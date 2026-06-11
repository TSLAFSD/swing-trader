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


def _fundamentals_rows(fund: Fundamentals, market: str, last_close: float) -> list[tuple[str, str]]:
    def num(v: float | None, fmt: str = "{:,.1f}") -> str:
        return "정보 없음" if v is None else fmt.format(v)

    cap = fund.market_cap
    if cap is None:
        cap_s = "정보 없음"
    elif market == "kr":
        cap_s = f"{cap / 1e12:,.1f}조원"
    else:
        cap_s = f"${cap / 1e9:,.1f}B"
    if fund.week52_high and fund.week52_low and fund.week52_high > fund.week52_low:
        pos = (last_close - fund.week52_low) / (fund.week52_high - fund.week52_low) * 100
        wk52 = f"{pos:.0f}% 위치"
    else:
        wk52 = "정보 없음"
    return [
        ("PER", num(fund.per)),
        ("PBR", num(fund.pbr)),
        ("시가총액", cap_s),
        ("배당수익률", "정보 없음" if fund.dividend_yield is None else f"{fund.dividend_yield:.2f}%"),
        ("52주 고저 대비", wk52),
        ("52주 최고/최저", f"{_fmt_price(fund.week52_high, market)} / {_fmt_price(fund.week52_low, market)}"),
    ]


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
    kelly_hint: str = "Phase 6에서 제공 예정",
    correlation_warning: str | None = None,
) -> Path:
    """Render one signal's HTML report to REPORTS_OUT_DIR.

    Returns:
        Path of the written file (random-hash name).
    """
    market = signal.market
    last = df_ind.iloc[-1]
    chart = build_chart_html(
        df_ind, markers=[{"date": signal.signal_date, "kind": "BUY", "price": signal.price}]
    )
    target = (
        _fmt_price(signal.suggested_take_profit, market)
        if signal.suggested_take_profit
        else ("ATR 추적 청산" if signal.exit_mode == "atr_trailing" else "전략 조건 청산")
    )
    template = _env.get_template("report.html.j2")
    html = template.render(
        name=signal.name,
        ticker=signal.ticker,
        market_label=MARKET_LABEL[market],
        issued_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        strategy_badges=[signal.strategy_id],
        strength=f"{signal.strength:.0f}",
        confidence_label=f"{confidence.score:.2f}",
        tags=signal.tags,
        chart_html=chart,
        indicator_lines=summarize_kr(last, market),
        fundamentals=_fundamentals_rows(fundamentals, market, float(last["close"])),
        reason=signal.reason,
        strategy_ranking=strategy_ranking or [],
        plan={
            "entry": _fmt_price(signal.price, market),
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
