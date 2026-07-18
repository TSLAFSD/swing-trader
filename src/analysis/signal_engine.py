"""Signal engine: orchestrates guards, strategies, quality layers, ranking.

Pipeline (per market, per scan):
  1. Per-ticker indicator computation — SEQUENTIAL, one ticker in memory
     (8GB dev-machine rule; the Actions runner follows the same code path).
  2. Guards: anomaly (1-day move beyond +-30% -> excluded + flagged),
     pre-scan price/liquidity floors, short-history exclusion per strategy.
  3. Strategy evaluation -> confluence merge.
  4. RS momentum percentile filter (bottom percentile dropped/downgraded).
  5. Regime downgrade (index trend + breadth).
  6. Earnings-gap warning tag (best-effort, signal tickers only).
  7. Rank by strength, keep top N.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from config import settings
from src.analysis import indicators as ind
from src.analysis.base_strategy import Signal
from src.analysis.registry import get_strategies
from src.analysis.regime import RegimeState, get_regime

logger = logging.getLogger(__name__)

# Rides on every observe-lane signal (card + report) so the label can never
# be lost between the scan and the reader.
OBSERVE_TAG = "🔍 관찰 — 검증 미통과 · 추천 아님"


@dataclass
class ScanResult:
    """Outcome of one market scan."""

    market: str
    scan_date: date
    signals: list[Signal]  # ranked, top N
    total_scanned: int
    anomalies: list[str] = field(default_factory=list)  # 데이터 이상 의심 tickers
    rs_dropped: list[str] = field(default_factory=list)
    breadth_pct: float | None = None
    regime: RegimeState | None = None
    signal_frames: dict[str, pd.DataFrame] = field(default_factory=dict)  # for reports
    references: list[Signal] = field(default_factory=list)  # observe lane, 추천 아님


def _passes_prescan(df: pd.DataFrame, market: str) -> bool:
    """Price floor + minimum average daily trading value (config)."""
    last_close = float(df["close"].iloc[-1])
    floor = settings.KR_MIN_PRICE if market == "kr" else settings.US_MIN_PRICE
    if last_close < floor:
        return False
    recent = df.tail(20)
    avg_value = float((recent["close"] * recent["volume"]).mean())
    min_value = (
        settings.KR_MIN_AVG_TRADING_VALUE if market == "kr" else settings.US_MIN_AVG_DOLLAR_VOLUME
    )
    return avg_value >= min_value


def _next_earnings_within(ticker: str, market: str, days: int) -> date | None:
    """Best-effort next-earnings lookup (yfinance). Missing data = None, never raises."""
    try:
        import yfinance as yf

        symbol = ticker if market == "us" else f"{ticker}.KS"
        cal = yf.Ticker(symbol).calendar or {}
        dates = cal.get("Earnings Date") or []
        horizon = date.today() + timedelta(days=days * 1.5)  # ~trading->calendar days
        for d in dates:
            d = d.date() if hasattr(d, "date") else d
            if date.today() <= d <= horizon:
                return d
    except Exception:
        logger.debug("earnings lookup failed for %s (best-effort)", ticker, exc_info=True)
    return None


def scan_market(
    market: str,
    ohlcv: pd.DataFrame,
    names: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
    enabled_only: bool = True,
    check_earnings: bool = True,
    fetch_regime: bool = True,
) -> ScanResult:
    """Run the full signal pipeline over one market's stored OHLCV.

    Args:
        market: "us" | "kr".
        ohlcv: Long-format canonical frame (store.load output).
        names: {ticker: display name}; ticker itself used when missing.
        config: strategies.yaml override (tests).
        enabled_only: False = run all strategies regardless of YAML enabled
            (validation/demo use only).
        check_earnings: Toggle the earnings tag (off in tests).
        fetch_regime: Toggle index/VIX network fetches (off in tests).

    Returns:
        ScanResult with ranked top-N signals and health-check metadata.
    """
    names = names or {}
    # include_observe only matters on the live path (enabled_only=True):
    # observe-lane strategies scan alongside enabled ones, but their signals
    # are reference-only (validation/demo runs already include everything).
    strategies = get_strategies(config, enabled_only=enabled_only, include_observe=enabled_only)
    # Normalize dtype: DuckDB returns datetime64, fetchers return datetime.date —
    # the per-ticker "has a bar on the latest trading day" guard needs equality.
    ohlcv = ohlcv.copy()
    ohlcv["date"] = pd.to_datetime(ohlcv["date"]).dt.date
    scan_date = ohlcv["date"].max()

    # Memory discipline (8GB rule): only per-ticker CLOSES (RS momentum) and
    # breadth counters survive the loop; full indicator frames are kept ONLY
    # for tickers that produced a signal (needed for reports).
    signal_frames: dict[str, pd.DataFrame] = {}
    closes: dict[str, pd.Series] = {}
    anomalies: list[str] = []
    raw_signals: list[Signal] = []
    breadth_above = breadth_total = 0
    total_scanned = 0

    tickers = sorted(ohlcv["ticker"].unique())
    logger.info("scan %s: %d tickers, %d strategies", market, len(tickers), len(strategies))
    grouped = ohlcv.groupby("ticker", sort=True)
    for ticker, df in grouped:  # sequential by design (8GB rule)
        df = df.sort_values("date").reset_index(drop=True)
        # Halted-ticker guard: must have a bar on the market's latest trading day.
        if df["date"].iloc[-1] != scan_date:
            continue
        if not _passes_prescan(df, market):
            continue
        df = ind.compute_indicators(df)
        total_scanned += 1
        closes[ticker] = df["close"]
        last = df.iloc[-1]
        if pd.notna(last["sma60"]):
            breadth_total += 1
            if last["close"] > last["sma60"]:
                breadth_above += 1

        last_move = last["pct_change_1d"]
        if pd.notna(last_move) and abs(last_move) > settings.ANOMALY_DAILY_MOVE_PCT:
            anomalies.append(ticker)
            logger.warning("anomaly guard: %s 1-day move %+.1f%% — excluded today", ticker, last_move)
            continue

        display = names.get(ticker, ticker)
        fired = False
        for strategy in strategies:
            if not strategy.eligible(df):
                continue
            try:
                sig = strategy.evaluate(df, ticker, display, market)
            except Exception:
                logger.exception("strategy %s crashed on %s", strategy.strategy_id, ticker)
                continue
            if sig is not None:
                if enabled_only and not strategy.enabled:  # observe lane
                    sig.is_reference = True
                    sig.tags.append(OBSERVE_TAG)
                raw_signals.append(sig)
                fired = True
        if fired:
            signal_frames[ticker] = df

    signals = raw_signals

    # Layer 1: cross-sectional RS momentum filter.
    rs_pct = ind.rs_momentum_percentile(closes)
    rs_dropped: list[str] = []
    filtered: list[Signal] = []
    for sig in signals:
        pct = rs_pct.get(sig.ticker)
        if pct is None:
            sig.tags.append("RS 모멘텀: 표본 부족")
            filtered.append(sig)
            continue
        sig.indicators["rs_percentile"] = round(pct, 1)
        if pct < settings.RS_PERCENTILE_FLOOR:
            if settings.RS_FLOOR_ACTION == "drop":
                rs_dropped.append(sig.ticker)
                logger.info("rs filter: dropped %s (percentile %.0f)", sig.ticker, pct)
                continue
            sig.strength = round(sig.strength * settings.RS_DOWNGRADE_FACTOR, 1)
            sig.tags.append(f"⚠️ 상대 모멘텀 하위 {pct:.0f}분위 — 강도 하향")
        filtered.append(sig)
    signals = filtered

    # Layer 2: regime downgrade.
    breadth = (breadth_above / breadth_total * 100.0) if breadth_total else float("nan")
    regime = get_regime(market, breadth) if fetch_regime else None
    if regime is not None and regime.downgrade_factor < 1.0:
        for sig in signals:
            sig.strength = round(sig.strength * regime.downgrade_factor, 1)
            sig.tags.append("⚠️ 시장 약세 국면 — 강도 하향")

    # Layer 4: earnings-gap warning (best-effort, never blocks).
    if check_earnings:
        for sig in signals:
            earnings = _next_earnings_within(sig.ticker, market, settings.EARNINGS_WARN_DAYS)
            if earnings is not None:
                sig.tags.append(f"⚠️ {earnings:%m/%d} 실적발표 예정 — 갭 리스크")

    signals.sort(key=lambda s: s.strength, reverse=True)
    # Observe lane: references never compete with recommendations for top-N.
    references = [s for s in signals if s.is_reference][: settings.OBSERVE_MAX_ITEMS]
    signals = [s for s in signals if not s.is_reference]
    top = signals[: settings.SCAN_TOP_N]
    logger.info(
        "scan %s done: %d scanned, %d signals (%d kept), %d references, %d anomalies, breadth %.1f%%",
        market, total_scanned, len(signals), len(top), len(references), len(anomalies),
        breadth if breadth == breadth else float("nan"),
    )
    kept = top + references
    return ScanResult(
        market=market,
        scan_date=scan_date,
        signals=top,
        total_scanned=total_scanned,
        anomalies=anomalies,
        rs_dropped=rs_dropped,
        breadth_pct=breadth,
        regime=regime,
        signal_frames={s.ticker: signal_frames[s.ticker] for s in kept if s.ticker in signal_frames},
        references=references,
    )
