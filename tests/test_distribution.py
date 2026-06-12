"""Distribution monitor tests (U3/C-2): mirrored UTAD on a mock holding."""

import pandas as pd

from src.risk.distribution import check_distribution
from tests.test_wyckoff_vpa import make_df, spring_frame


def utad_frame() -> pd.DataFrame:
    """Padded sell-side mirror of the spring pattern (UTAD + demand exhaustion)."""
    pattern = spring_frame()
    pad = make_df([100.0] * 120)
    df = pd.concat([pad, pattern], ignore_index=True)
    out = df.copy()
    out["close"] = 200.0 - df["close"]
    out["open"] = 200.0 - df["open"]
    out["high"] = 200.0 - df["low"]
    out["low"] = 200.0 - df["high"]
    out["date"] = pd.bdate_range("2024-06-03", periods=len(out)).date
    return out


class TestDistribution:
    def test_alert_with_exhaustion_merged(self) -> None:
        text = check_distribution(utad_frame(), "테스트", "TEST")
        assert text is not None
        assert "분산 징후" in text and "UTAD" in text
        assert "수요 고갈 동반" in text  # merged into ONE message

    def test_silent_before_climax(self) -> None:
        df = utad_frame().iloc[:140].reset_index(drop=True)  # climax not yet formed
        assert check_distribution(df, "테스트", "TEST") is None

    def test_silent_on_plain_uptrend(self) -> None:
        closes = [100 + 0.2 * i for i in range(200)]
        assert check_distribution(make_df(closes), "테스트", "TEST") is None
