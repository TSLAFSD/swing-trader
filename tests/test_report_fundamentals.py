"""Zero-price defense: halted-day rows (low=0) must not break the report.

Regression for the 2026-07-02 KR scan crash: a halted-day bar with low=0.0
reached the store, _own_52w() returned own_low=0.0, and the external-52w
consistency check divided by zero (html_builder.py `fund.week52_low / own_low`).
"""

import pandas as pd
import pytest

from src.data.fundamentals import Fundamentals
from src.data.kr_fetcher import _canonical
from src.report.html_builder import _fundamentals_rows, _own_52w


def _frame_with_zero_low(n: int = 260) -> pd.DataFrame:
    high = [110.0] * n
    low = [90.0] * n
    low[100] = 0.0  # halted-day artifact
    high[100] = 0.0
    return pd.DataFrame({"high": high, "low": low, "close": [100.0] * n})


def test_fundamentals_rows_survives_zero_low() -> None:
    df = _frame_with_zero_low()
    fund = Fundamentals(ticker="000000", week52_high=110.0, week52_low=90.0)
    rows = _fundamentals_rows(fund, "kr", 100.0, df)  # must not raise
    assert any("52주" in key for key, _ in rows)


def test_own_52w_ignores_nonpositive_rows() -> None:
    high, low = _own_52w(_frame_with_zero_low())
    assert high == pytest.approx(110.0)
    assert low == pytest.approx(90.0)


def test_own_52w_all_bad_rows_is_nan_and_rows_still_build() -> None:
    df = pd.DataFrame({"high": [0.0] * 10, "low": [0.0] * 10, "close": [0.0] * 10})
    high, low = _own_52w(df)
    assert high != high and low != low  # NaN
    fund = Fundamentals(ticker="000000", week52_high=110.0, week52_low=90.0)
    _fundamentals_rows(fund, "kr", 100.0, df)  # must not raise


def test_store_load_excludes_archived_zero_price_rows(tmp_path) -> None:
    """Rows archived before the fetcher-level filter must be excluded on load."""
    from datetime import date

    from src.data.store import ParquetStore

    store = ParquetStore(root=tmp_path)
    frame = pd.DataFrame(
        {
            "ticker": ["000000"] * 3,
            "date": [date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1)],
            "open": [100.0, 0.0, 102.0],
            "high": [110.0, 0.0, 112.0],
            "low": [90.0, 0.0, 92.0],
            "close": [105.0, 0.0, 107.0],
            "volume": [1000.0, 0.0, 1200.0],
            "source": ["test"] * 3,
        }
    )
    store.upsert(frame, "kr")
    loaded = store.load("kr")
    assert len(loaded) == 2
    assert (loaded["low"] > 0).all()


def test_kr_canonical_drops_nonpositive_price_rows() -> None:
    raw = pd.DataFrame(
        {
            "open": [100.0, 0.0, 102.0],
            "high": [110.0, 0.0, 112.0],
            "low": [90.0, 0.0, 92.0],
            "close": [105.0, 0.0, 107.0],
            "volume": [1000.0, 0.0, 1200.0],
        },
        index=pd.to_datetime(["2026-06-29", "2026-06-30", "2026-07-01"]),
    )
    out = _canonical(raw, "000000", "test")
    assert len(out) == 2
    assert (out["low"] > 0).all()
