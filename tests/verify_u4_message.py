"""U4 verification: new vs legacy message format + character-count comparison.

Builds both formats from the same stored-data scan (signals enriched exactly
as main._scan does) and prints them verbatim with char counts.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.base_strategy import Signal, load_strategy_config
from src.analysis.grading import composite_grade, contrarian_indicators, entry_zone_top
from src.analysis.registry import get_strategies
from src.analysis.signal_engine import scan_market
from src.analysis.wyckoff_vpa import diagnose_stage_count, wyckoff_badge_kr
from src.backtest.confidence import ticker_confidence
from src.data.store import ParquetStore
from src.data.universe import load_us_universe
from src.notify.messages import _fmt_price, holdings_summary, scan_message

logging.basicConfig(level=logging.WARNING)


def legacy_card(rank: int, sig: Signal, url: str | None, conf_label: str | None) -> str:
    """Pre-U4 card format (verbatim copy for the comparison)."""
    market = sig.market
    target = "ATR추적" if sig.exit_mode == "atr_trailing" else "조건청산"
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
    lines += [f"   {t}" for t in sig.tags]
    if url:
        lines.append(f"   📄 {url}")
    return "\n".join(lines)


def main() -> None:  # noqa: D103
    store = ParquetStore()
    uni = load_us_universe(refresh=False)
    names = dict(zip(uni["ticker"], uni["name"]))
    result = scan_market("us", store.load("us"), names, fetch_regime=False, check_earnings=False)
    strategies = {s.strategy_id: s for s in get_strategies(enabled_only=False)}
    vpa = load_strategy_config()["strategies"]["wyckoff_spring"]["params"]["vpa"]
    conf_labels = {}
    url = "https://tslafsd.github.io/swing-trader/2026-06-12-XXXX-abcd1234.html"
    for sig in result.signals:
        df = result.signal_frames[sig.ticker]
        conf = ticker_confidence(df, strategies[sig.strategy_id], sig.ticker, "us")
        conf_labels[sig.ticker] = f"{conf.score:.2f}"
        sig.strength = round(sig.strength * max(conf.score, 0.1), 1)
        grade = composite_grade(sig.strength, conf.score, 1.0)
        sig.grade, sig.grade_basis = grade.letter, grade.basis_kr
        sig.wyckoff_badge = wyckoff_badge_kr(diagnose_stage_count(df, vpa))
        atr = df["atr14"].iloc[-1]
        sig.entry_zone_top = entry_zone_top(sig.price, None if atr != atr else float(atr))
        sig.contrarian = contrarian_indicators(df)

    urls = {s.ticker: url for s in result.signals}
    new_msg = scan_message(result, urls, conf_labels, filtered_count=1)
    legacy = "\n\n".join(
        legacy_card(i, s, urls[s.ticker], conf_labels.get(s.ticker))
        for i, s in enumerate(result.signals[:5], 1)
    )
    print("===== 신규 포맷 (U4) =====")
    print(new_msg)
    print("\n===== 구 포맷 카드 (동일 시그널) =====")
    print(legacy)
    print("\n===== 보유 요약 (신규, mock) =====")
    rows = [
        {"ticker": "AAPL", "name": "Apple", "market": "us", "entry_price": 280.0,
         "current": 291.58, "pnl_pct": 4.1, "near_stop": False},
        {"ticker": "005930", "name": "삼성전자", "market": "kr", "entry_price": 310000.0,
         "current": 299000.0, "pnl_pct": -3.5, "near_stop": True},
    ]
    print(holdings_summary(rows))
    card_new = "\n\n".join(
        scan_message(result, urls, conf_labels).split("\n\n")[1:2]
    )
    print(f"\n글자수 비교 — 신규 카드부 {len(new_msg)}자 vs 구 카드부 {len(legacy)}자 "
          f"(메시지 전체 기준; 카드 1건: 신규 {len(card_new)} vs 구 {len(legacy.split(chr(10)+chr(10))[0])})")


if __name__ == "__main__":
    main()
