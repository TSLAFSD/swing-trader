"""Korean Telegram message formats (spec §9).

Anti-overload rule: scan messages carry AT MOST the top 5 ranked signals;
ranks 6-10 collapse into one line. Health check goes out EVERY scan, even
with zero signals — silence must mean breakage, never success.
"""

import logging
import traceback
from datetime import datetime, timedelta, timezone

from src.analysis.base_strategy import Signal
from src.analysis.signal_engine import ScanResult

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
MARKET_EMOJI = {"us": "🇺🇸", "kr": "🇰🇷"}
MARKET_KR = {"us": "미국", "kr": "한국"}
TOP_N_IN_MESSAGE = 5


def _fmt_price(value: float | None, market: str) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}원" if market == "kr" else f"${value:,.2f}"


def _signal_card(rank: int, sig: Signal, url: str | None, conf_label: str | None) -> str:
    market = sig.market
    target = (
        _fmt_price(sig.suggested_take_profit, market)
        if sig.suggested_take_profit
        else ("ATR추적" if sig.exit_mode == "atr_trailing" else "조건청산")
    )
    key_ind = ""
    for key in ("rsi2", "rsi14", "zscore20", "adx14"):
        if key in sig.indicators:
            key_ind = f" · {key} {sig.indicators[key]:.1f}"
            break
    lines = [
        f"{rank}. {sig.name}({sig.ticker}) — {sig.strategy_id} 강도 {sig.strength:.0f}"
        + (f" · 신뢰도 {conf_label}" if conf_label else ""),
        f"   매수 {_fmt_price(sig.price, market)} · 손절 {_fmt_price(sig.suggested_stop_loss, market)}"
        f" · 목표 {target}{key_ind}",
    ]
    for tag in sig.tags:
        lines.append(f"   {tag}")
    if url:
        lines.append(f"   📄 {url}")
    return "\n".join(lines)


def scan_message(
    result: ScanResult,
    report_urls: dict[str, str],
    confidence_labels: dict[str, str] | None = None,
    preliminary: bool = False,
    kr_third_source_used: bool = False,
    filtered_count: int = 0,
) -> str:
    """Build the per-scan message: health line + top-5 cards + collapsed rest."""
    confidence_labels = confidence_labels or {}
    flag = MARKET_EMOJI[result.market]
    header = f"{flag} {MARKET_KR[result.market]} 스캔 완료 · {result.scan_date}"
    if preliminary:
        header += "\n⚠️ 예비(미확정) — 종가 확정 전 참고용입니다"
    filtered_note = f" (필터 제외 {filtered_count}건)" if filtered_count else ""
    body = [header, f"✅ {result.total_scanned:,}종목 스캔 · 시그널 {len(result.signals)}개{filtered_note}"]
    if result.regime:
        body.append(f"🌐 {result.regime.label_kr}")
    if result.anomalies:
        body.append(
            f"⚠️ 데이터 이상 의심 (분할/병합/오류 가능): {', '.join(result.anomalies[:5])}"
            + (f" 외 {len(result.anomalies) - 5}건" if len(result.anomalies) > 5 else "")
        )
    if kr_third_source_used:
        body.append("⚠️ 3차 소스(yfinance) 사용 — 데이터 정확도 주의")
    if result.signals:
        body.append("")
        for i, sig in enumerate(result.signals[:TOP_N_IN_MESSAGE], 1):
            body.append(_signal_card(i, sig, report_urls.get(sig.ticker), confidence_labels.get(sig.ticker)))
            body.append("")
        rest = result.signals[TOP_N_IN_MESSAGE:]
        if rest:
            body.append(f"외 {len(rest)}건 — 리포트 참조: " + ", ".join(s.ticker for s in rest))
    return "\n".join(body).strip()


def sell_alert(ticker: str, name: str, market: str, reason: str, entry_price: float, current: float) -> str:
    """Sell recommendation for a held position."""
    pnl = (current / entry_price - 1) * 100
    return (
        f"🔴 매도 검토: {name}({ticker})\n"
        f"사유: {reason}\n"
        f"현재 {_fmt_price(current, market)} · 수익률 {pnl:+.1f}% (진입 {_fmt_price(entry_price, market)})"
    )


def holdings_summary(rows: list[dict]) -> str:
    """One-line-per-position daily holdings summary (Telegram ONLY, never reports)."""
    if not rows:
        return ""
    lines = ["💼 보유 현황"]
    for r in rows:
        lines.append(
            f"· {r['name']}({r['ticker']}) {r['pnl_pct']:+.1f}% — "
            f"손절까지 {r['to_stop_pct']:+.1f}% · 목표까지 {r['to_target']}"
        )
    return "\n".join(lines)


def gap_guard_message(items: list[dict]) -> str:
    """Consolidated US pre-market gap check (spec §11.1)."""
    lines = [f"🇺🇸 프리마켓 갭 체크 ({datetime.now(KST).strftime('%H:%M')} KST)"]
    for it in items:
        t, sig_p, cur_p, gap = it["ticker"], it["signal_price"], it["current_price"], it["gap_pct"]
        if abs(gap) < it["threshold"]:
            lines.append(f"✅ {t} 시그널가 대비 {gap:+.1f}% 이내 — 계획대로 진입 가능")
        elif gap > 0:
            lines.append(
                f"⚠️ {t} 시그널가 ${sig_p:,.2f} → 현재 ${cur_p:,.2f} ({gap:+.1f}%) — 추격 매수 주의\n"
                f"   현재가 기준 재계산: 손절 ${it['new_stop']:,.2f}"
                + (f" · 목표 ${it['new_target']:,.2f}" if it.get("new_target") else "")
            )
        else:
            lines.append(f"⚠️ {t} 시그널가 대비 {gap:+.1f}% — 시그널 근거 훼손 가능, 진입 보류 권고")
    return "\n".join(lines)


def error_alert(job_kr: str, log_tail: str) -> str:
    """Failure alert a non-developer can copy-paste into Claude Code (spec §11).

    Includes: one-line Korean summary, exception location, raw traceback tail.
    """
    exc_type = exc_line = ""
    lines = [ln for ln in log_tail.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith(("Traceback",)):
            break
        if not exc_type and ":" in ln and not ln.startswith(" "):
            exc_type = ln.strip()[:160]
        if not exc_line and ln.strip().startswith("File "):
            exc_line = ln.strip()[:160]
    tail = "\n".join(lines[-10:])
    return (
        f"🚨 {job_kr} 중 오류가 발생했습니다\n"
        f"위치: {exc_line or '(traceback 없음)'}\n"
        f"오류: {exc_type or '(불명)'}\n\n"
        f"아래 전체를 복사해 Claude Code에 붙여넣고 \"고쳐줘\"라고 하세요:\n"
        f"```\n[{job_kr} 실패]\n{tail}\n```"
    )


def format_exception(job_kr: str, exc: BaseException) -> str:
    """error_alert() variant for in-process exceptions."""
    return error_alert(job_kr, "".join(traceback.format_exception(exc)))
