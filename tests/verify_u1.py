"""U1 verification: 131290 fundamentals fix + send-cutoff before/after demo."""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.indicators import compute_indicators
from src.analysis.registry import get_strategies
from src.analysis.signal_engine import scan_market
from src.backtest.confidence import ticker_confidence
from src.data.fundamentals import fetch_fundamentals
from src.data.kr_fetcher import fetch_kr_ohlcv
from src.data.store import ParquetStore
from src.data.universe import load_us_universe
from src.notify.send_filter import filter_for_send
from src.report.html_builder import _fundamentals_rows

logging.basicConfig(level=logging.WARNING)


def main() -> None:  # noqa: D103
    print("=== (A-1) 131290 티에스이 — 새 펀더멘털 행 ===")
    ohlcv, _ = fetch_kr_ohlcv(["131290"], start=date.today() - timedelta(days=420))
    df = compute_indicators(ohlcv.sort_values("date").reset_index(drop=True))
    fund = fetch_fundamentals("131290", yf_symbol="131290.KQ", market="kr")
    for key, value in _fundamentals_rows(fund, "kr", float(df["close"].iloc[-1]), df):
        print(f"  {key}: {value}")
    print("\n=== (A-1) 동일 종목, 구버그 경로(.KS 외부 데이터) 주입 시 — 괴리 게이트 ===")
    fund_bad = fetch_fundamentals("131290", yf_symbol="131290.KS", market="kr")
    for key, value in _fundamentals_rows(fund_bad, "kr", float(df["close"].iloc[-1]), df):
        print(f"  {key}: {value}")

    print("\n=== (A-2) 발송 컷오프 전후 비교 (US 저장 데이터) ===")
    store = ParquetStore()
    uni = load_us_universe(refresh=False)
    names = dict(zip(uni["ticker"], uni["name"]))
    result = scan_market("us", store.load("us"), names, fetch_regime=False, check_earnings=False)
    strategies = {s.strategy_id: s for s in get_strategies(enabled_only=False)}
    confs = {}
    for sig in result.signals:
        frame = result.signal_frames.get(sig.ticker)
        strategy = strategies.get(sig.strategy_id)
        if frame is None or strategy is None:
            continue
        conf = ticker_confidence(frame, strategy, sig.ticker, "us")
        confs[sig.ticker] = conf
        sig.strength = round(sig.strength * max(conf.score, 0.1), 1)
    result.signals.sort(key=lambda s: s.strength, reverse=True)
    print(f"[컷오프 전] {len(result.signals)}건:")
    for s in result.signals:
        c = confs.get(s.ticker)
        stop_w = abs(s.price - s.suggested_stop_loss) / s.price * 100 if s.suggested_stop_loss else 0
        print(f"  {s.ticker}: 강도 {s.strength} · 표본 {c.n_trades if c else '?'} · "
              f"PF {c.profit_factor:.2f} · 손절폭 -{stop_w:.0f}%" if c else f"  {s.ticker}")
    send, excluded = filter_for_send(result.signals, confs)
    print(f"[컷오프 후 발송] {len(send)}건: {[s.ticker for s in send]}")
    for d in excluded:
        print(f"  제외 {d.signal.ticker}: {'; '.join(d.reasons)}")
    print(f"헬스체크 표기: 시그널 {len(send)}개 (필터 제외 {len(excluded)}건)")


if __name__ == "__main__":
    main()
