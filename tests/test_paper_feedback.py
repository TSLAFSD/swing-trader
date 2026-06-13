"""P-C tests: feedback efficacy, feature buckets, exit analysis, suggestions."""

import json

import pandas as pd
import pytest

from src.paper import feedback
from src.paper.portfolio import TRADES_COLUMNS


def sig_rows(grade: str, strategy: str, fwds: list[float], rsi: float = 50.0) -> list[dict]:
    return [
        {
            "grade": grade,
            "strategy_id": strategy,
            "features_json": json.dumps({"rsi14": rsi}),
            "fwd_10d": f,
        }
        for f in fwds
    ]


def trade_rows(specs: list[tuple]) -> pd.DataFrame:
    base = {c: None for c in TRADES_COLUMNS}
    rows = []
    for ticker, ret, mae, mfe in specs:
        r = dict(base)
        r.update(ticker=ticker, return_pct=ret, mae_pct=mae, mfe_pct=mfe)
        rows.append(r)
    return pd.DataFrame(rows, columns=TRADES_COLUMNS)


EMPTY_TRADES = pd.DataFrame(columns=TRADES_COLUMNS)


class TestEfficacy:
    def test_grade_efficacy_order_and_hit(self) -> None:
        df = pd.DataFrame(
            sig_rows("A", "breakout", [0.02, -0.01, 0.03, -0.02, 0.01])
            + sig_rows("B", "breakout", [0.01, 0.02, 0.03, 0.04, -0.01])
        )
        ge = feedback.grade_efficacy(df)
        assert [r["grade"] for r in ge] == ["A", "B"]
        a = next(r for r in ge if r["grade"] == "A")
        assert a["n"] == 5
        assert a["hit"] == pytest.approx(3 / 5)

    def test_strategy_efficacy(self) -> None:
        df = pd.DataFrame(sig_rows("A", "breakout", [0.01, -0.01]) + sig_rows("A", "pullback", [0.02]))
        se = feedback.strategy_efficacy(df)
        assert {r["strategy_id"] for r in se} == {"breakout", "pullback"}


class TestFeatureBuckets:
    def test_terciles(self) -> None:
        rows = []
        for i in range(12):
            rsi = 30 + i * 5
            rows.append(sig_rows("A", "breakout", [0.01 if rsi < 60 else -0.01], rsi=rsi)[0])
        b = feedback.feature_buckets(pd.DataFrame(rows), "rsi14")
        assert len(b) >= 2
        assert all("range" in x and "hit" in x for x in b)

    def test_below_min_sample_returns_empty(self) -> None:
        df = pd.DataFrame(sig_rows("A", "breakout", [0.01, -0.01], rsi=40.0))
        assert feedback.feature_buckets(df, "rsi14") == []


class TestExitAnalysis:
    def test_metrics(self) -> None:
        df = trade_rows([("A", 10.0, -3.0, 14.0), ("B", 5.0, -2.0, 9.0), ("C", -8.0, -9.0, 1.0)])
        ex = feedback.exit_analysis(df)
        assert ex["n"] == 3 and ex["n_win"] == 2
        assert ex["winner_giveback_median"] == pytest.approx(4.0)  # (14-10),(9-5)


class TestSuggestions:
    def test_grade_inversion_flagged(self) -> None:
        df = pd.DataFrame(
            sig_rows("A", "breakout", [0.01, -0.01, -0.02, -0.03, -0.04, 0.02, -0.01, -0.02, -0.03, -0.05])
            + sig_rows("B", "breakout", [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, -0.01, -0.02, 0.07, 0.08])
        )
        report = feedback.build_feedback(df, EMPTY_TRADES)
        titles = [s["title"] for s in report["suggestions"]]
        assert any("A등급 적중률이 B등급보다 낮음" in t for t in titles)

    def test_small_sample_no_suggestions(self) -> None:
        df = pd.DataFrame(sig_rows("A", "breakout", [-0.01, -0.02]) + sig_rows("B", "breakout", [0.01, 0.02]))
        report = feedback.build_feedback(df, EMPTY_TRADES)
        assert report["suggestions"] == []


class TestRenderAndPersist:
    def test_full_render(self) -> None:
        df = pd.DataFrame(
            sig_rows("A", "breakout", [-0.01] * 8 + [0.01, 0.02])
            + sig_rows("B", "breakout", [0.01] * 8 + [-0.01, -0.02])
        )
        report = feedback.build_feedback(df, EMPTY_TRADES)
        txt = feedback.feedback_kr(report, full=True)
        assert "무엇이 통했나" in txt
        assert "검토 제안" in txt  # grade inversion present

    def test_compact_render(self) -> None:
        report = feedback.build_feedback(pd.DataFrame(sig_rows("A", "breakout", [0.01])), EMPTY_TRADES)
        assert "인사이트" in feedback.feedback_kr(report, full=False)

    def test_empty_render(self) -> None:
        report = feedback.build_feedback(pd.DataFrame(columns=["grade", "strategy_id", "features_json", "fwd_10d"]), EMPTY_TRADES)
        assert "아직 데이터가 없습니다" in feedback.feedback_kr(report, full=True)

    def test_write_findings_valid_json(self, tmp_path) -> None:
        report = feedback.build_feedback(
            pd.DataFrame(sig_rows("A", "breakout", [0.01, -0.01])), EMPTY_TRADES
        )
        path = tmp_path / "feedback.json"
        feedback.write_findings(report, path=path)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert "grade_efficacy" in loaded and "suggestions" in loaded
