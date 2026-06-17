"""AI analysis bridge prompt (U6/Part F) — MANUAL copy only, by design.

The report embeds a fully-rendered Korean prompt (real values substituted at
build time) behind a sticky copy button. NO automatic LLM API calls — the
owner pastes it into their own AI chat. Position data is NEVER included
(rule 5): only the signal's own suggested values.
"""

import logging

import pandas as pd

from src.analysis.base_strategy import Signal
from src.analysis.wyckoff_vpa import weis_waves
from src.backtest.confidence import ConfidenceReport

logger = logging.getLogger(__name__)

DAILY_BARS = 50
WEEKLY_BARS = 30
RECENT_WAVES = 10

_ROLE = (
    "당신은 와이코프 방법론과 기술적 분석 전문가입니다. 패턴 암기가 아닌 "
    "세력의 의도와 공급/수요 고갈을 검증하는 관점으로 아래 종목을 분석하세요."
)

_COT = """분석 지시 — 아래 단계를 순서대로, 각 단계의 근거를 명시하며 검증하세요:
① 기술적 구조: 일봉과 주봉의 구조(추세·박스권·주요 레벨)가 서로 부합하는가
② 거래량 흐름과 와이코프 단계: 위 Weis Wave·클라이맥스 수치가 매집/분산 어느 가설을 지지하는가
③ 지표 합치/충돌: 제공된 지표들 사이의 모순을 반드시 명시하라 (모순이 없다고 가정하지 말 것)
④ 시장 국면 적합성: 현재 국면에서 이 전략 유형이 작동할 조건인가
⑤ 매수 범위·손절 독립 도출: 위에 제공된 일봉/주봉 데이터에서 직접 지지·저항 레벨을 찾고,
   ATR·Weis Wave 구조·와이코프 저점을 근거로 적정 매수 범위·손절가·1차 목표가를 당신이 직접 산출하라.
   위 '시스템 기계적 제안'은 전략 규칙이 자동 계산한 참고값일 뿐이다 — 그대로 베끼지 말고,
   각 가격이 어느 레벨/지표에서 나왔는지 근거를 반드시 명시하라.
⑥ 진입 타당성과 무효화 조건: 진입한다면 어떤 근거이고, 어느 가격/조건에서 이 해석이 깨지는가.
   당신의 도출값이 시스템 제안과 다르면 어디서·왜 갈라지는지 설명하라.

[최종 출력 형식]
- 독립 매수 범위: (하단) ~ (상단) — 근거:
- 독립 손절가: (가격) — 근거:
- 1차 목표가: (가격) — 근거:
- 시스템 제안 대비: (동의 / 조정 — 이유)
- 종합 판단: (진입 가능 / 관망 / 회피 + 한 줄 요약)

본 분석은 교육적 목적이며 투자 자문이 아닙니다."""


def _csv_block(df: pd.DataFrame, n: int, label: str) -> str:
    rows = [f"[{label} 최근 {min(n, len(df))}봉] date,open,high,low,close,volume"]
    for r in df.tail(n).itertuples():
        rows.append(
            f"{r.date},{r.open:.2f},{r.high:.2f},{r.low:.2f},{r.close:.2f},{int(r.volume)}"
        )
    return "\n".join(rows)


def _waves_block(daily: pd.DataFrame, zigzag_pct: float) -> str:
    waves = weis_waves(daily, zigzag_pct=zigzag_pct)
    if waves.empty:
        return "[Weis Wave] 파동 없음 (변동폭 부족)"
    lines = [f"[Weis Wave · zigzag {zigzag_pct}% · 최근 {RECENT_WAVES}개] 방향,봉수,누적거래량,가격변화"]
    for w in waves.tail(RECENT_WAVES).itertuples():
        direction = "상승" if w.direction == 1 else "하락"
        lines.append(f"{direction},{w.bars},{int(w.cum_volume)},{w.price_range:.2f}")
    return "\n".join(lines)


def _snapshot_block(df_ind: pd.DataFrame) -> str:
    row = df_ind.iloc[-1]
    parts = []
    for key, label in (
        ("close", "종가"), ("sma20", "SMA20"), ("sma60", "SMA60"), ("sma200", "SMA200"),
        ("rsi14", "RSI14"), ("rsi2", "RSI2"), ("macd_hist", "MACD히스토그램"),
        ("zscore20", "z-score(20)"), ("atr14", "ATR14"), ("adx14", "ADX14"),
    ):
        v = row.get(key)
        if v is not None and v == v:
            parts.append(f"{label}={v:,.2f}")
    vol_ma = row.get("vol_ma20")
    if vol_ma and vol_ma == vol_ma and vol_ma > 0:
        parts.append(f"거래량/20일평균={row['volume'] / vol_ma:.2f}배")
    return "[지표 스냅샷] " + " · ".join(parts)


def build_ai_prompt(
    signal: Signal,
    df_ind: pd.DataFrame,
    weekly: pd.DataFrame,
    vpa_stages: list[dict],
    zigzag_pct: float,
    regime_label: str,
    confidence: ConfidenceReport,
) -> str:
    """Render the full manual-copy analysis prompt with real values."""
    market = "한국(KRX)" if signal.market == "kr" else "미국"
    zone = (
        f"{signal.price:,.2f} ~ {signal.entry_zone_top:,.2f}"
        if signal.entry_zone_top else f"{signal.price:,.2f}"
    )
    stop = f"{signal.suggested_stop_loss:,.2f}" if signal.suggested_stop_loss else "전략 조건 청산"
    stages = "\n".join(
        f"- {s['label']}: {'충족' if s['ok'] else '미충족'} ({s['value']})" for s in vpa_stages
    )
    contrarian = (
        "\n".join(f"- {c}" for c in signal.contrarian) if signal.contrarian else "- 없음"
    )
    conf_line = (
        f"표본 {confidence.n_trades}건 · 승률 {confidence.win_rate * 100:.0f}% · "
        f"PF {confidence.profit_factor:.2f} · MDD {confidence.max_drawdown_pct:.1f}% · {confidence.label_kr}"
        if confidence.n_trades > 0 else "과거 시그널 없음 — 백테스트 신뢰도 평가 불가"
    )
    daily = df_ind[["date", "open", "high", "low", "close", "volume"]]
    return f"""{_ROLE}

[기본 정보]
종목: {signal.name}({signal.ticker}) · 시장: {market} · 기준일: {signal.signal_date}
현재가: {signal.price:,.2f} · 전략: {signal.strategy_id} · 종합 등급: {signal.grade or "-"} ({signal.grade_basis or "-"})

{_csv_block(daily, DAILY_BARS, "일봉")}

{_csv_block(weekly, WEEKLY_BARS, "주봉")}

[와이코프 3단계 정량 진단]
{stages}

{_waves_block(daily, zigzag_pct)}

{_snapshot_block(df_ind)}
[시장 국면] {regime_label}
[역행 지표]
{contrarian}
[백테스트 신뢰도] {conf_line}

[시스템 기계적 제안 — 참고용, 검증 대상 (그대로 따르지 말 것)]
매수 범위: {zone} · 제안 손절: {stop}

{_COT}"""
