"""Feedback loop (P-C) — "what worked", read-only analysis.

Reads the two P-A/P-B datasets and reports which setups actually paid off:
  - signals.parquet (every recommendation + grade/confidence/regime/features)
    joined with forward_returns -> the BROAD labeled study (grade/strategy/
    feature-bucket efficacy over +10d).
  - paper/trades.parquet -> realistic exit analysis (MAE/MFE: were stops too
    tight, did winners give back too much).

HARD RULE (CLAUDE.md activation policy): this tool only SUGGESTS. It never
flips `enabled` or rewrites params. Suggestions are sample-gated and framed as
manual-review items; Claude/the owner apply changes by hand. Findings are also
written to a machine-readable feedback.json for later Claude analysis.
"""

import json
import logging
import math

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

FWD = "fwd_10d"  # horizon used for efficacy (matches CB_MEAN_FWD10 circuit breaker)
BUCKET_FEATURES = ("rsi14", "zscore20", "atr14")  # entry indicators worth slicing
WEAK_HIT_RATE = 0.45  # strategy hit rate below this -> re-validation suggestion
GRADE_ORDER = {"A": 0, "B": 1, "C": 2}


def _san(value):
    """JSON-safe scalar: NaN/inf -> None, numpy -> python."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return num if math.isfinite(num) else None


def _hit_avg(series_fwd: pd.Series) -> tuple[float, float]:
    """(+10d hit rate, mean +10d return %) for a group's forward returns."""
    s = pd.to_numeric(series_fwd, errors="coerce").dropna()
    if s.empty:
        return float("nan"), float("nan")
    return float((s > 0).mean()), float(s.mean() * 100.0)


def grade_efficacy(signals_fwd: pd.DataFrame) -> list[dict]:
    """Per-grade hit rate / avg forward return — does A actually beat B beat C?"""
    if signals_fwd is None or signals_fwd.empty or "grade" not in signals_fwd.columns:
        return []
    df = signals_fwd.dropna(subset=[FWD]) if FWD in signals_fwd.columns else signals_fwd.iloc[0:0]
    out = []
    for grade, grp in df.groupby("grade"):
        if not str(grade).strip():
            continue
        hit, avg = _hit_avg(grp[FWD])
        out.append({"grade": str(grade), "n": int(len(grp)), "hit": hit, "avg": avg})
    return sorted(out, key=lambda r: GRADE_ORDER.get(r["grade"], 9))


def strategy_efficacy(signals_fwd: pd.DataFrame) -> list[dict]:
    """Per-strategy hit rate / avg forward return."""
    if signals_fwd is None or signals_fwd.empty or "strategy_id" not in signals_fwd.columns:
        return []
    df = signals_fwd.dropna(subset=[FWD]) if FWD in signals_fwd.columns else signals_fwd.iloc[0:0]
    out = []
    for sid, grp in df.groupby("strategy_id"):
        hit, avg = _hit_avg(grp[FWD])
        out.append({"strategy_id": str(sid), "n": int(len(grp)), "hit": hit, "avg": avg})
    return sorted(out, key=lambda r: r["n"], reverse=True)


def _features_frame(signals_fwd: pd.DataFrame, keys) -> pd.DataFrame:
    """Explode features_json into columns alongside the forward return."""
    recs = []
    for _, row in signals_fwd.iterrows():
        try:
            feats = json.loads(row.get("features_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            feats = {}
        rec = {k: feats.get(k) for k in keys}
        rec[FWD] = row.get(FWD)
        recs.append(rec)
    return pd.DataFrame(recs)


def feature_buckets(signals_fwd: pd.DataFrame, feature: str, n_buckets: int = 3) -> list[dict]:
    """Tercile hit rate / avg return across an entry indicator's range."""
    if signals_fwd is None or signals_fwd.empty or FWD not in signals_fwd.columns:
        return []
    ff = _features_frame(signals_fwd, [feature]).dropna(subset=[feature, FWD])
    if len(ff) < settings.PAPER_FEEDBACK_MIN_SAMPLE:
        return []
    try:
        ff["bucket"] = pd.qcut(ff[feature], n_buckets, duplicates="drop")
    except ValueError:
        return []
    out = []
    for bucket, grp in ff.groupby("bucket", observed=True):
        hit, avg = _hit_avg(grp[FWD])
        out.append(
            {"range": f"{bucket.left:.1f}~{bucket.right:.1f}", "n": int(len(grp)), "hit": hit, "avg": avg}
        )
    return out


def exit_analysis(trades: pd.DataFrame) -> dict:
    """MAE/MFE diagnostics from realized virtual trades (stop/target tuning)."""
    if trades is None or trades.empty:
        return {}
    ret = pd.to_numeric(trades["return_pct"], errors="coerce")
    mae = pd.to_numeric(trades["mae_pct"], errors="coerce")
    mfe = pd.to_numeric(trades["mfe_pct"], errors="coerce")
    win = ret > 0
    giveback = mfe - ret  # how much of the peak gain was handed back
    return {
        "n": int(len(trades)),
        "n_win": int(win.sum()),
        "winner_mae_median": _san(mae[win].median()),
        "loser_mae_median": _san(mae[~win].median()),
        "winner_mfe_median": _san(mfe[win].median()),
        "winner_giveback_median": _san(giveback[win].median()),
    }


def _suggestions(grades: list[dict], strategies: list[dict], exits: dict) -> list[dict]:
    """Sample-gated, manual-apply review items (never auto-applied)."""
    min_n = settings.PAPER_FEEDBACK_MIN_SAMPLE
    out: list[dict] = []
    # Grade monotonicity: a higher grade should not hit LESS than a lower one.
    big = {g["grade"]: g for g in grades if g["n"] >= min_n and g["hit"] == g["hit"]}
    if "A" in big and "B" in big and big["A"]["hit"] < big["B"]["hit"]:
        out.append({
            "kind": "suggest",
            "title": "A등급 적중률이 B등급보다 낮음",
            "detail": f"A {big['A']['hit'] * 100:.0f}% < B {big['B']['hit'] * 100:.0f}% — 등급 산출 가중치(GRADE_W_*) 재검토 권장.",
        })
    # Weak strategy: persistently low hit rate over a meaningful sample.
    for s in strategies:
        if s["n"] >= min_n and s["hit"] == s["hit"] and s["hit"] < WEAK_HIT_RATE:
            out.append({
                "kind": "suggest",
                "title": f"{s['strategy_id']} 적중률 저조",
                "detail": f"{s['n']}건 적중 {s['hit'] * 100:.0f}% (<{WEAK_HIT_RATE * 100:.0f}%) — 재검증/비활성 검토.",
            })
    # Exit tuning hints (only with enough trades).
    if exits.get("n", 0) >= min_n:
        wmae = exits.get("winner_mae_median")
        if wmae is not None and wmae <= -8.0:
            out.append({
                "kind": "info",
                "title": "승자도 깊게 눌렸다 되돌아옴",
                "detail": f"승자 MAE 중앙값 {wmae:.1f}% — 손절을 너무 타이트하게 잡으면 승자도 잘릴 수 있음.",
            })
        gb = exits.get("winner_giveback_median")
        if gb is not None and gb >= 5.0:
            out.append({
                "kind": "info",
                "title": "이익 반납이 큼",
                "detail": f"승자 최고점 대비 반납 중앙값 {gb:.1f}%p — 트레일링/익절 타이밍 검토.",
            })
    return out


def build_feedback(signals_fwd: pd.DataFrame, trades: pd.DataFrame) -> dict:
    """Assemble the full feedback report (sections + suggestions)."""
    grades = grade_efficacy(signals_fwd)
    strategies = strategy_efficacy(signals_fwd)
    buckets = {f: feature_buckets(signals_fwd, f) for f in BUCKET_FEATURES}
    buckets = {f: b for f, b in buckets.items() if b}
    exits = exit_analysis(trades)
    n_signals = 0 if signals_fwd is None else int(len(signals_fwd))
    return {
        "n_signals": n_signals,
        "n_trades": exits.get("n", 0),
        "grade_efficacy": grades,
        "strategy_efficacy": strategies,
        "feature_buckets": buckets,
        "exit_analysis": exits,
        "suggestions": _suggestions(grades, strategies, exits),
    }


def _deep_san(obj):
    """Recursively replace non-finite floats with None so the JSON is valid."""
    if isinstance(obj, dict):
        return {k: _deep_san(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_san(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def write_findings(report: dict, path=None) -> None:
    """Persist machine-readable findings (rides the data branch for Claude/P-C)."""
    path = path or settings.PAPER_FEEDBACK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_deep_san(report), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("feedback findings written: %s", path)


def _eff_lines(rows: list[dict], key: str) -> list[str]:
    lines = []
    for r in rows:
        hit = f"{r['hit'] * 100:.0f}%" if r["hit"] == r["hit"] else "—"
        avg = f"{r['avg']:+.1f}%" if r["avg"] == r["avg"] else "—"
        lines.append(f"· {r[key]}: {r['n']}건 · 적중 {hit} · 평균 {avg}")
    return lines


def feedback_kr(report: dict, full: bool = True) -> str:
    """Korean render. full=True -> on-demand report; full=False -> weekly digest."""
    sugg = report.get("suggestions", [])
    if not full:
        if report["n_signals"] < settings.PAPER_FEEDBACK_MIN_SAMPLE and report["n_trades"] == 0:
            return f"💡 인사이트: 표본 부족 (시그널 {report['n_signals']}건) — 더 쌓이면 분석 시작."
        if not sugg:
            return f"💡 인사이트: 특이 제안 없음 (시그널 {report['n_signals']}건 · 청산 {report['n_trades']}건)."
        head = sugg[0]["title"]
        extra = f" 외 {len(sugg) - 1}건" if len(sugg) > 1 else ""
        return f"💡 인사이트: 검토 제안 {len(sugg)}건 — {head}{extra} (상세는 `feedback`)."

    if report["n_signals"] == 0 and report["n_trades"] == 0:
        return "💡 페이퍼 트레이딩 분석: 아직 데이터가 없습니다 (확정 스캔이 쌓이면 시작)."
    out = ["💡 페이퍼 트레이딩 분석 (무엇이 통했나 · +10일 선행수익 기준)"]
    if report["grade_efficacy"]:
        out += ["", "[등급별]"] + _eff_lines(report["grade_efficacy"], "grade")
    if report["strategy_efficacy"]:
        out += ["", "[전략별]"] + _eff_lines(report["strategy_efficacy"], "strategy_id")
    for feat, rows in report["feature_buckets"].items():
        seg = [f"{r['range']}: 적중 {r['hit'] * 100:.0f}%/평균 {r['avg']:+.1f}%" for r in rows]
        out += ["", f"[{feat} 구간별]", "· " + " | ".join(seg)]
    ex = report["exit_analysis"]
    if ex:
        out += ["", f"[청산 분석 (가상 청산 {ex['n']}건, 승 {ex['n_win']})]"]
        if ex.get("winner_mae_median") is not None:
            out.append(f"· 승자 MAE 중앙값 {ex['winner_mae_median']:.1f}% (반등 전 최대 하락)")
        if ex.get("winner_giveback_median") is not None:
            out.append(f"· 승자 이익반납 중앙값 {ex['winner_giveback_median']:.1f}%p (최고점 대비)")
    if sugg:
        out += ["", "🔧 검토 제안 (수동 적용):"] + [f"· {s['title']} — {s['detail']}" for s in sugg]
    out += ["", "※ 표본이 작을수록 신뢰 낮음. enabled/파라미터 변경은 수동 승인."]
    return "\n".join(out)
