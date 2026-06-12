"""U4 tests: composite grade, entry zone, contrarian indicators."""

import pandas as pd
import pytest

from src.analysis.grading import (
    composite_grade,
    contrarian_indicators,
    entry_zone_top,
    regime_score,
)
from tests.test_indicators import make_ohlcv
from src.analysis.indicators import compute_indicators


class TestCompositeGrade:
    def test_hand_computed_a(self) -> None:
        # 80*0.5 + 0.8*100*0.3 + 100*0.2 = 40+24+20 = 84 -> A
        g = composite_grade(80.0, 0.8, 1.0)
        assert g.letter == "A" and g.value == pytest.approx(84.0)
        assert "84" in g.basis_kr and "→ A" in g.basis_kr

    def test_hand_computed_b_with_one_downgrade(self) -> None:
        # 60*0.5 + 0.5*100*0.3 + 50*0.2 = 30+15+10 = 55 -> B
        g = composite_grade(60.0, 0.5, 0.7)  # breadth-only downgrade
        assert g.letter == "B" and g.value == pytest.approx(55.0)

    def test_c_with_double_downgrade(self) -> None:
        # 40*0.5 + 0.3*100*0.3 + 0*0.2 = 29 -> C
        g = composite_grade(40.0, 0.3, 0.35)
        assert g.letter == "C"

    def test_regime_score_mapping(self) -> None:
        assert regime_score(None) == 100.0
        assert regime_score(1.0) == 100.0
        assert regime_score(0.5) == 50.0
        assert regime_score(0.7) == 50.0
        assert regime_score(0.35) == 0.0


class TestEntryZone:
    def test_atr_cap_when_tighter(self) -> None:
        # 0.5*ATR(2.0)=1.0 < price*3%=3.0 -> top = 101.0
        assert entry_zone_top(100.0, 2.0) == pytest.approx(101.0)

    def test_pct_cap_when_atr_wide(self) -> None:
        # 0.5*ATR(10)=5.0 > 3.0 -> top = 103.0
        assert entry_zone_top(100.0, 10.0) == pytest.approx(103.0)

    def test_missing_atr_falls_back_to_pct(self) -> None:
        assert entry_zone_top(100.0, None) == pytest.approx(103.0)


class TestContrarian:
    def test_clean_uptrend_has_few(self) -> None:
        df = compute_indicators(make_ohlcv([100.0 + 0.3 * i for i in range(260)]))
        labels = contrarian_indicators(df)
        assert all("200일선 아래" not in label for label in labels)

    def test_downtrend_flags_sma200_and_slope(self) -> None:
        df = compute_indicators(make_ohlcv([200.0 - 0.3 * i for i in range(260)]))
        labels = contrarian_indicators(df)
        assert any("200일선 아래" in label for label in labels)
        assert any("60일선 하향" in label for label in labels)

    def test_overheat_flags_rsi_and_zscore(self) -> None:
        closes = [100.0] * 240 + [100 + 3 * i for i in range(1, 21)]  # vertical spike
        df = compute_indicators(make_ohlcv(closes))
        labels = contrarian_indicators(df)
        assert any("RSI 70" in label for label in labels)
        assert any("z-score" in label for label in labels)
