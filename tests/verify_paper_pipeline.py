"""Real-data verification of the paper portfolio (P-A/P-B/P-C).

Runs against the LOCAL store + signals.parquet — no network, no Telegram, no
publish. Exercises: signals forward returns + feedback, a paper open/mark cycle
through compute_indicators + evaluate_position on REAL OHLCV, the paper.html
render, and feedback.json. Prints PASS lines; raises on failure.

Run: .venv/bin/python -m tests.verify_paper_pipeline
"""

import json
import tempfile
from pathlib import Path

import pandas as pd

from src.analysis.base_strategy import Signal
from src.backtest import tracker
from src.data.store import ParquetStore
from src.paper import feedback, portfolio
from src.report import paper_report


def main() -> None:
    store = ParquetStore()
    counts = {m: len(store.load(m)) for m in ("us", "kr")}
    print(f"[store] rows: us={counts['us']:,} kr={counts['kr']:,}")
    market = "kr" if counts["kr"] else ("us" if counts["us"] else "")
    assert market, "no local market data to verify against"

    # 1) signals.parquet -> forward returns -> feedback (real recommendations)
    sigs = tracker.load_signals()
    print(f"[signals] {len(sigs)} rows · enrichment cols present: {'features_json' in sigs.columns}")
    fwd = tracker.forward_returns(store, sigs)
    fb = feedback.build_feedback(fwd, portfolio.load_trades(path=Path("/nonexistent")))
    print(
        f"[feedback] n_signals={fb['n_signals']} "
        f"strategies={len(fb['strategy_efficacy'])} suggestions={len(fb['suggestions'])}"
    )
    for r in fb["strategy_efficacy"][:4]:
        hit = f"{r['hit'] * 100:.0f}%" if r["hit"] == r["hit"] else "—"
        print(f"    · {r['strategy_id']}: {r['n']}건 적중 {hit}")
    print("    compact: " + feedback.feedback_kr(fb, full=False))

    # 2) paper open/mark cycle on a REAL ticker (temp paths only)
    data = store.load(market)
    data["date"] = pd.to_datetime(data["date"]).dt.date
    sizes = data.groupby("ticker").size()
    ticker = str(sizes[sizes >= 60].index[0])
    tdf = data[data["ticker"] == ticker].sort_values("date")
    entry_bar = tdf.iloc[-30]  # leave ~29 later real bars to mark/exit against
    entry_price = float(entry_bar["close"])
    sig = Signal(
        ticker=ticker, name=ticker, market=market, strategy_id="breakout", direction="BUY",
        strength=72.0, price=entry_price, signal_date=entry_bar["date"], indicators={"rsi14": 55.0},
        suggested_stop_loss=round(entry_price * 0.90, 4), suggested_take_profit=round(entry_price * 1.30, 4),
        exit_mode="fixed", grade="A", grade_value=82.0, confidence=0.6, regime_factor=1.0,
    )
    with tempfile.TemporaryDirectory() as tmp:
        op, tp = Path(tmp) / "open.json", Path(tmp) / "trades.parquet"
        out = portfolio.update_paper_portfolio(market, [sig], store, open_path=op, trades_path=tp)
        print(f"[paper open] {ticker} @ {entry_price:,.2f} → opened={out['n_opened']} open_total={out['open_total']}")
        assert out["n_opened"] == 1, "expected one virtual open"

        out2 = portfolio.update_paper_portfolio(market, [], store, open_path=op, trades_path=tp)
        held = portfolio.load_open(op)
        if out2["closed"]:
            c = out2["closed"][0]
            print(f"[paper exit] real-data exit: {c['ticker']} {c['return_pct']:+.1f}% · {c['exit_reason']} · {c['holding_days']}일")
        else:
            h = held[0]
            assert h["last_mark_date"] >= h["entry_date"], "mark did not advance"
            print(f"[paper mark] held {h['ticker']} 평가 {h['unrealized_pct']:+.1f}% · MAE {h['mae_pct']:+.1f}% · MFE {h['mfe_pct']:+.1f}%")

        # 3) dashboard render + 4) findings.json
        trades_df = portfolio.load_trades(tp)
        path = paper_report.build_paper_report(trades_df, held, benchmark_pct=1.2, out_dir=Path(tmp))
        html = path.read_text(encoding="utf-8")
        assert "가상 포트폴리오" in html
        print(f"[dashboard] paper.html rendered: {path.stat().st_size:,} bytes ✓")
        fpath = Path(tmp) / "feedback.json"
        feedback.write_findings(fb, path=fpath)
        json.loads(fpath.read_text(encoding="utf-8"))
        print("[findings] feedback.json valid ✓")

    print("\nVERIFY OK ✅  paper pipeline runs end-to-end on REAL data (no network/Telegram/publish)")


if __name__ == "__main__":
    main()
