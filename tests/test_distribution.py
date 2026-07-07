"""Distribution monitor tests (U3/C-2): mirrored UTAD on a mock holding."""

import pandas as pd

from src.risk.distribution import (
    DIST_TAG_PREFIX,
    candidate_tag_kr,
    check_distribution,
    distribution_evidence,
)
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


class TestDistributionEvidence:
    def test_evidence_on_utad_frame(self) -> None:
        ev = distribution_evidence(utad_frame())
        assert ev is not None
        assert ev.climax_fresh or ev.exhaustion_fresh
        assert ev.volume_ratio > 0
        assert ev.test_volume_ratio is not None  # exhaustion present in fixture

    def test_no_evidence_on_plain_uptrend(self) -> None:
        closes = [100 + 0.2 * i for i in range(200)]
        assert distribution_evidence(make_df(closes)) is None

    def test_candidate_tag_is_one_line_korean(self) -> None:
        ev = distribution_evidence(utad_frame())
        tag = candidate_tag_kr(ev)
        assert tag.startswith(DIST_TAG_PREFIX)
        assert "\n" not in tag
        assert "설거지" in tag

    def test_recent_bars_window_respected(self) -> None:
        # A huge window keeps stale evidence alive; the default window is what
        # makes iloc[:140] silent in test_silent_before_climax.
        assert distribution_evidence(utad_frame(), recent_bars=10_000) is not None
