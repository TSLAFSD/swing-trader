# Entry Diversification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diversify entry character per the 2026-07-07 spec — distribution ("설거지") badge on all signal candidates, breakout overheat-guard adoption via the owner-approved criterion, and expanded-sample re-validation of zscore_meanrev / pullback-v2(distribution-veto) / wyckoff_spring.

**Architecture:** Refactor `src/risk/distribution.py` into a structured evidence detector with two Korean formatters (held-position alert = existing behavior; candidate tag = new). Wire the tag into the U4 enrichment loop in `main.py` (tags auto-render in Telegram cards and HTML reports). Validation work reuses the existing Phase-4 harness (`src/backtest/run_validation.py` + `validate_strategy`) with a new `--strategy` CLI filter and `VAL_SAMPLE_US` 80→160.

**Tech Stack:** Python 3.12 venv (`.venv/bin/python`), pytest, pandas, existing backtesting harness. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-07-entry-diversification-design.md`

## Global Constraints

- Always run tests via `.venv/bin/pytest tests/ -q` before every commit; full suite must be green.
- Code/comments/logs in English; user-facing strings (tags, badges, messages) in Korean.
- `logging` only, no `print` in `src/` (scripts under `tests/` may print — existing pattern).
- Thresholds/params live ONLY in `config/strategies.yaml` or `config/settings.py` — never in code.
- YAML `enabled:` / param changes ONLY after attaching verbatim validation output (reporting-integrity). Backtests are historical — never imply guaranteed future returns; survivorship-bias disclosure stays.
- Parity invariant: absent optional YAML params ⇒ byte-identical baseline behavior (test-enforced).
- Sequential per-ticker processing, no local multiprocessing (8GB rule).
- Owner-approved (2026-07-07) guard adoption criterion: OoS PF ≥ baseline ×1.05 AND OoS WR ≥ baseline −1%p AND OoS n ≥ ×0.7 — post-hoc origin must be disclosed in YAML comments.
- Telegram top-5 rule and "badge, never block" decision (spec §소유자 결정 2) must hold.

---

### Task 1: Structured distribution evidence + candidate tag (Part 3 core)

**Files:**
- Modify: `src/risk/distribution.py`
- Test: `tests/test_distribution.py`

**Interfaces:**
- Consumes: `src/analysis/wyckoff_vpa.py` detectors (unchanged).
- Produces:
  - `@dataclass(frozen=True) DistributionEvidence` — fields: `level: float`, `volume_ratio: float`, `recovery_type: str`, `climax_fresh: bool`, `exhaustion_fresh: bool`, `test_volume_ratio: float | None`
  - `distribution_evidence(df: pd.DataFrame, recent_bars: int = RECENT_BARS) -> DistributionEvidence | None`
  - `candidate_tag_kr(ev: DistributionEvidence) -> str` (starts with `DIST_TAG_PREFIX`)
  - `DIST_TAG_PREFIX = "⚠️ 분산 의심"` (module constant)
  - `check_distribution(df, name, ticker) -> str | None` — signature and output text UNCHANGED (existing tests are the parity gate).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_distribution.py`:

```python
from src.risk.distribution import (
    DIST_TAG_PREFIX,
    candidate_tag_kr,
    check_distribution,
    distribution_evidence,
)


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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/bin/pytest tests/test_distribution.py -v`
Expected: 3 existing tests PASS, 4 new tests FAIL with `ImportError: cannot import name 'distribution_evidence'`.

- [ ] **Step 3: Implement** — rewrite `src/risk/distribution.py` (detection body moves verbatim from the old `check_distribution`):

```python
"""Distribution monitor (U3/C-2) — sell-side VPA evidence, two consumers.

Held positions: confirmed scans call check_distribution() (Korean alert,
warning only — never an automatic sell). Signal candidates (2026-07-07
Part 3): the scan loop calls distribution_evidence() + candidate_tag_kr()
to badge suspected distribution ("설거지") — badge only, NEVER a block
(re-accumulation looks identical while forming; a later spring signal
re-recommends it if so).
"""

import logging
from dataclasses import dataclass

import pandas as pd

from src.analysis.base_strategy import load_strategy_config
from src.analysis.wyckoff_vpa import (
    detect_buying_climax,
    detect_demand_exhaustion,
    detect_liquidity_high,
    weis_waves,
)

logger = logging.getLogger(__name__)

RECENT_BARS = 5  # climax older than this is stale — no alert
DIST_TAG_PREFIX = "⚠️ 분산 의심"


@dataclass(frozen=True)
class DistributionEvidence:
    """Sell-side VPA evidence for one ticker (UTAD-pattern)."""

    level: float  # broken liquidity high
    volume_ratio: float  # climax volume vs its MA
    recovery_type: str  # "rejection_wick" | close-regression variant
    climax_fresh: bool
    exhaustion_fresh: bool
    test_volume_ratio: float | None  # None when no demand exhaustion


def distribution_evidence(
    df: pd.DataFrame, recent_bars: int = RECENT_BARS
) -> DistributionEvidence | None:
    """Detect a recent UTAD (+ optional demand exhaustion) on one ticker.

    Args:
        df: Adjusted OHLCV (canonical columns), ascending dates.
        recent_bars: Freshness window; evidence older than this returns None.

    Returns:
        Evidence when a fresh UTAD fired, else None.
    """
    vpa = load_strategy_config()["strategies"]["wyckoff_spring"]["params"]["vpa"]
    if len(df) < vpa["lookback"] + vpa["pivot_strength"]:
        return None
    level = detect_liquidity_high(
        df, lookback=vpa["lookback"], pivot_strength=vpa["pivot_strength"],
        equal_high_pct=vpa["equal_low_pct"],
    )
    if level is None:
        return None
    climax = detect_buying_climax(
        df, level.level, vol_ma_days=vpa["vol_ma_days"],
        vol_mult=vpa["vol_mult"], wick_body_ratio=vpa["wick_body_ratio"],
    )
    if climax is None:
        return None
    waves = weis_waves(df, zigzag_pct=vpa["zigzag_pct"])
    exhaustion = detect_demand_exhaustion(
        waves, climax, retest_window=vpa["retest_window"], exhaust_ratio=vpa["exhaust_ratio"],
    )
    n = len(df)
    climax_fresh = climax.sweep_idx >= n - recent_bars
    exhaustion_fresh = False
    if exhaustion is not None:
        pos = df.index[df["date"] == exhaustion.retest_date]
        exhaustion_fresh = bool(len(pos)) and (n - 1 - pos[0]) <= recent_bars
    if not (climax_fresh or exhaustion_fresh):
        return None
    return DistributionEvidence(
        level=level.level,
        volume_ratio=climax.volume_ratio,
        recovery_type=climax.recovery_type,
        climax_fresh=climax_fresh,
        exhaustion_fresh=exhaustion_fresh,
        test_volume_ratio=exhaustion.test_volume_ratio if exhaustion else None,
    )


def candidate_tag_kr(ev: DistributionEvidence) -> str:
    """One-line Korean badge for a SIGNAL CANDIDATE (advisory, never blocks)."""
    kind = "윗꼬리 거부" if ev.recovery_type == "rejection_wick" else "종가 회귀"
    tail = " · 수요 고갈 동반" if ev.test_volume_ratio is not None else ""
    return (
        f"{DIST_TAG_PREFIX} — 고점 돌파 후 거래량 {ev.volume_ratio:.1f}배 + {kind}"
        f" (UTAD/설거지 가능){tail} · 재매집일 수도 있어 참고만"
    )


def check_distribution(df: pd.DataFrame, name: str, ticker: str) -> str | None:
    """Korean distribution warning for one held ticker, or None.

    Args:
        df: Adjusted OHLCV (canonical columns), ascending dates.
        name: Display name.
        ticker: Ticker code.

    Returns:
        Alert text when a recent UTAD fired (exhaustion merged in), else None.
    """
    ev = distribution_evidence(df)
    if ev is None:
        return None
    kind = "윗꼬리 거부" if ev.recovery_type == "rejection_wick" else "종가 회귀"
    text = (
        f"🚨 [분산 징후] {name}({ticker}) — 고점 {ev.level:,.0f} 상향 이탈 후 "
        f"거래량 {ev.volume_ratio:.1f}배 + {kind} (UTAD 의심), 익절 검토 권고"
    )
    if ev.test_volume_ratio is not None:
        text += (
            f"\n   수요 고갈 동반: 재상승 시도 거래량이 클라이맥스의 "
            f"{ev.test_volume_ratio:.0%}에 불과 — 상승 동력 소진 신호"
        )
    return text
```

- [ ] **Step 4: Run the distribution tests**

Run: `.venv/bin/pytest tests/test_distribution.py -v`
Expected: all 7 PASS (3 pre-existing = parity gate for the refactor).

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/pytest tests/ -q` — expected all green.

```bash
git add src/risk/distribution.py tests/test_distribution.py
git commit -m "refactor(risk): structured distribution evidence + candidate badge formatter"
```

---

### Task 2: Wire the distribution badge into the scan + health-line count (Part 3 wiring)

**Files:**
- Modify: `main.py` (U4 enrichment block, directly after `sig.contrarian = contrarian_indicators(df_ind)` — currently line ~149)
- Modify: `src/notify/messages.py` (`scan_message` health line)
- Test: `tests/test_send_filter.py` is unrelated — add to `tests/verify_u4_message.py`? NO — add a new focused test file `tests/test_distribution_badge.py`

**Interfaces:**
- Consumes: `distribution_evidence`, `candidate_tag_kr`, `DIST_TAG_PREFIX` from Task 1; `Signal.tags` (rendered by `_signal_card` tag loop and `html_builder` `tags=signal.tags` — no renderer change needed).
- Produces: scan health line gains `· 분산 의심 N건` when N > 0.

- [ ] **Step 1: Write the failing test** — create `tests/test_distribution_badge.py`:

```python
"""Part 3 (2026-07-07): distribution badge on signal candidates — display only."""

from datetime import date

from src.analysis.base_strategy import Signal
from src.analysis.signal_engine import ScanResult
from src.notify import messages
from src.risk.distribution import DIST_TAG_PREFIX


def _sig(ticker: str, tags: list[str]) -> Signal:
    return Signal(
        ticker=ticker, name=ticker, market="us", strategy_id="breakout",
        direction="BUY", strength=70.0, price=100.0,
        signal_date=date(2026, 7, 7), tags=tags,
    )


def _result(signals: list[Signal]) -> ScanResult:
    return ScanResult(
        market="us", scan_date=date(2026, 7, 7), signals=signals,
        total_scanned=100,
    )


class TestDistributionBadgeInMessage:
    def test_health_line_counts_badged_signals(self) -> None:
        tagged = _sig("AAA", [f"{DIST_TAG_PREFIX} — 고점 돌파 후 거래량 3.0배"])
        clean = _sig("BBB", [])
        text = messages.scan_message(_result([tagged, clean]), {})
        assert "분산 의심 1건" in text
        assert f"   {DIST_TAG_PREFIX}" in text  # tag renders inside the card

    def test_no_count_when_no_badges(self) -> None:
        text = messages.scan_message(_result([_sig("AAA", [])]), {})
        assert "분산 의심" not in text
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_distribution_badge.py -v`
Expected: `test_health_line_counts_badged_signals` FAILS on `"분산 의심 1건" in text` (the tag line itself already renders via the existing tag loop); second test PASSES.

- [ ] **Step 3: Implement the health-line count** in `src/notify/messages.py` — add import and modify `scan_message`:

At the top, with the other imports:

```python
from src.risk.distribution import DIST_TAG_PREFIX
```

In `scan_message`, replace the signal-count body line:

```python
    filtered_note = f" (필터 제외 {filtered_count}건)" if filtered_count else ""
    dist_n = sum(
        1 for s in result.signals if any(t.startswith(DIST_TAG_PREFIX) for t in s.tags)
    )
    dist_note = f" · 분산 의심 {dist_n}건" if dist_n else ""
    body = [
        header,
        f"✅ {result.total_scanned:,}종목 스캔 · 시그널 {len(result.signals)}개{filtered_note}{dist_note}",
    ]
```

- [ ] **Step 4: Wire the badge in `main.py`** — in the U4 enrichment block, immediately after `sig.contrarian = contrarian_indicators(df_ind)`:

```python
            # Part 3 (2026-07-07): distribution ("설거지") badge — advisory only,
            # never blocks or re-ranks (could be re-accumulation; a later spring
            # signal re-recommends it if so).
            from src.risk.distribution import candidate_tag_kr, distribution_evidence

            dist_ev = distribution_evidence(df_ind)
            if dist_ev is not None:
                sig.tags.append(candidate_tag_kr(dist_ev))
```

(Same lazy-import style as the surrounding block. Inside the per-ticker `try` — a VPA crash on one ticker must not kill the scan, matching the existing guard.)

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/test_distribution_badge.py tests/test_distribution.py -v`
Expected: all PASS.

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/pytest tests/ -q` — expected green.

```bash
git add main.py src/notify/messages.py tests/test_distribution_badge.py
git commit -m "feat(scan): distribution (설거지) badge on signal candidates + health-line count"
```

---

### Task 3: Part 4 verification — VPA context already rendered (no code)

Discovery during planning: the spec's Part 4 is ALREADY implemented by U4/U5 —
`Signal.wyckoff_badge` is computed per signal (`main.py` ~line 146), shown in the
Telegram card (`messages.py:37`), and the HTML report renders the full buy-side
stage checklist + weekly context (`html_builder.py:187` → `report.html.j2` lines
102–108, via `lw_chart.vpa_diagnosis`). This task VERIFIES and documents; it must
not add code (YAGNI).

**Files:**
- Modify: `docs/superpowers/specs/2026-07-07-entry-diversification-design.md` (append execution-log note)

- [ ] **Step 1: Verify rendering paths exist**

Run: `grep -n "wyckoff_badge" src/notify/messages.py src/report/html_builder.py && grep -n "vpa.stages" src/report/templates/report.html.j2`
Expected: hits in all three files.

- [ ] **Step 2: Run the report/message test files**

Run: `.venv/bin/pytest tests/test_feed.py tests/test_report_fundamentals.py -q`
Expected: PASS.

- [ ] **Step 3: Append to the spec** under a new `## 실행 결과 (진행 중)` section:

```markdown
## 실행 결과 (2026-07-07 진행 로그)

### Part 4 — 코드 변경 없음 (기구현 확인)

VPA 컨텍스트는 U4/U5에서 이미 구현되어 있음을 확인: 텔레그램 카드 와이코프 배지
(messages.py), 리포트 VPA 단계 체크리스트 + 주봉 컨텍스트 (report.html.j2 —
lw_chart.vpa_diagnosis). 추가 구현은 YAGNI로 생략. Part 3의 분산 배지가
매도측(sell-side) 컨텍스트를 보완한다.
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-07-entry-diversification-design.md
git commit -m "docs: Part 4 (VPA context) verified as already implemented in U4/U5"
```

---

### Task 4: `backtest --strategy` CLI filter

Lets Tasks 5 and 7 validate ONE strategy without re-running all six (each full run is hours of compute).

**Files:**
- Modify: `src/backtest/run_validation.py`
- Modify: `main.py` (argparse `backtest` subparser + dispatch)
- Test: `tests/test_backtest.py` (append)

**Interfaces:**
- Produces: `filter_strategies(strategies: list, only: str | None) -> list` in `run_validation.py`; `run(smoke: bool = False, only: str | None = None)` — `only` filters by `strategy_id`, unknown id raises `ValueError`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_backtest.py`:

```python
class TestStrategyFilter:
    def test_filter_keeps_only_requested(self) -> None:
        from src.analysis.registry import get_strategies
        from src.backtest.run_validation import filter_strategies

        strategies = get_strategies(enabled_only=False)
        kept = filter_strategies(strategies, "zscore_meanrev")
        assert [s.strategy_id for s in kept] == ["zscore_meanrev"]

    def test_filter_none_keeps_all(self) -> None:
        from src.analysis.registry import get_strategies
        from src.backtest.run_validation import filter_strategies

        strategies = get_strategies(enabled_only=False)
        assert filter_strategies(strategies, None) == list(strategies)

    def test_filter_unknown_raises(self) -> None:
        import pytest

        from src.analysis.registry import get_strategies
        from src.backtest.run_validation import filter_strategies

        with pytest.raises(ValueError, match="unknown strategy"):
            filter_strategies(get_strategies(enabled_only=False), "nope")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_backtest.py -v -k StrategyFilter`
Expected: FAIL with `ImportError: cannot import name 'filter_strategies'`.

- [ ] **Step 3: Implement** in `src/backtest/run_validation.py`:

Add after `build_frames`:

```python
def filter_strategies(strategies: list, only: str | None) -> list:
    """Keep only the requested strategy_id (None = all).

    Args:
        strategies: get_strategies() output.
        only: strategy_id to isolate, or None.

    Returns:
        Filtered list.

    Raises:
        ValueError: only does not match any registered strategy.
    """
    if only is None:
        return list(strategies)
    kept = [s for s in strategies if s.strategy_id == only]
    if not kept:
        raise ValueError(f"unknown strategy id: {only!r}")
    return kept
```

Change `run` signature and add the filter right after `strategies = get_strategies(...)`:

```python
def run(smoke: bool = False, only: str | None = None) -> dict[str, GateReport]:
    """Run the full validation suite; returns {strategy_id: GateReport}.

    Args:
        smoke: Tiny sample / fewer MC runs — debug only, never gates YAML.
        only: Validate a single strategy_id (None = all registered).
    """
    config = load_strategy_config()
    strategies = filter_strategies(get_strategies(config, enabled_only=False), only)
```

In `main.py`: `backtest.add_argument("--strategy", default=None)` next to the existing `--smoke`, and change the dispatch call (`elif args.command == "backtest":` branch) to pass `only=args.strategy` into `run(...)`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_backtest.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/pytest tests/ -q` — green.

```bash
git add src/backtest/run_validation.py main.py tests/test_backtest.py
git commit -m "feat(backtest): --strategy filter for single-strategy validation runs"
```

---

### Task 5: Part 1 — breakout overheat-guard Phase-4 re-pass (procedure)

The guard code exists (`strategy_breakout.py` optional params, parity-tested).
Owner-approved criterion (2026-07-07): OoS PF ≥ ×1.05 AND WR ≥ −1%p AND n ≥ ×0.7,
applied to the 7/2 grid ⇒ sole candidate **max_ext_pct=15** (PF ×1.10, WR −0.3%p,
n 0.78×). This task runs the full Phase-4 gates for breakout WITH the guard;
adoption only on PASS.

**Files:**
- Create: `tests/validate_breakout_guard.py` (runner script, `compare_breakout_guards.py` pattern)
- Modify (conditional, PASS only): `config/strategies.yaml` breakout block
- Modify: spec execution log

**Interfaces:**
- Consumes: `validate_strategy(cls, config, frames, market_of, index_series) -> GateReport`, `format_report`, `build_frames`, `fetch_index_series` (all existing).

- [ ] **Step 1: Create `tests/validate_breakout_guard.py`**:

```python
"""Part 1 (2026-07-07): full Phase-4 gates for breakout WITH max_ext_pct=15.

Owner-approved selection criterion (2026-07-07, POST-HOC — defined after the
2026-07-02 grid results were known; disclosed per reporting-integrity):
    OoS PF >= baseline x1.05 AND OoS WR >= baseline -1%p AND OoS n >= x0.7
Sole passer on that grid: max_ext_pct=15. This script is the ADOPTION gate:
the guarded breakout must re-pass every Phase-4 gate before YAML changes.

Results are historical; survivorship bias applies (current universe only).
Invoked via: .venv/bin/python tests/validate_breakout_guard.py
"""

import copy
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from src.analysis.base_strategy import load_strategy_config
from src.analysis.strategy_breakout import BreakoutStrategy
from src.backtest.run_validation import build_frames, fetch_index_series
from src.backtest.validation import format_report, validate_strategy

logging.basicConfig(level=logging.INFO)


def main() -> None:  # noqa: D103
    config = copy.deepcopy(load_strategy_config())
    config["strategies"]["breakout"]["params"]["max_ext_pct"] = 15.0
    frames = build_frames("us", settings.VAL_SAMPLE_US)
    index = fetch_index_series("us", settings.HISTORY_YEARS)
    print(f"breakout + max_ext_pct=15 — US sample {len(frames)} (GATING)")
    print("주의: 생존 편향(현재 유니버스 기준) — 결과는 과거 성과이며 미래 보장 없음")
    report = validate_strategy(
        BreakoutStrategy, config, frames, {t: "us" for t in frames}, index
    )
    print(format_report(report))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it, capture verbatim output** (long-running; ~30–60 min locally)

Run: `.venv/bin/python tests/validate_breakout_guard.py 2>&1 | tee /tmp/guard_phase4.txt`
Expected: a full `format_report` gate table ending in PASS or FAIL.

- [ ] **Step 3: Decision — apply ONLY the matching branch**

**If PASS:** edit `config/strategies.yaml` breakout block — add under `params:`:

```yaml
      max_ext_pct: 15.0  # overheat guard, adopted 2026-07-07 — owner-approved
                         # POST-HOC criterion (PF>=x1.05 AND WR>=-1%p AND n>=x0.7,
                         # set after seeing the 7/2 grid); full Phase-4 re-passed
                         # same date, verbatim output in the 07-07 spec log.
```

**If FAIL:** do NOT touch params; record the verdict + verbatim gate table in the spec execution log ("개선 없음"도 결과).

- [ ] **Step 4: Append verbatim output to the spec execution log** (both branches) under `### Part 1 — 과열 가드 Phase-4 재검증`, in a fenced block, untrimmed.

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/pytest tests/ -q` — green (YAML param addition must not break parity tests — guards are optional keys; if any test pins the breakout param set, honor the failure and investigate before committing).

```bash
git add tests/validate_breakout_guard.py config/strategies.yaml docs/superpowers/specs/2026-07-07-entry-diversification-design.md
git commit -m "feat(strategy): breakout overheat guard Phase-4 verdict recorded (adopted only on PASS)"
```

---

### Task 6: Expand the gating sample — `VAL_SAMPLE_US` 80 → 160

**Files:**
- Modify: `config/settings.py`
- Modify: spec execution log (one line noting the change + rationale)

- [ ] **Step 1: Edit** `config/settings.py`:

```python
VAL_SAMPLE_US = 160  # 2026-07-07 owner-approved expansion (was 80): OoS sample
                     # floor VAL_MIN_TRADES_OOS=20 was unreachable for sparse
                     # strategies (zscore n=14, spring n=12 on the 07-02 run).
VAL_SAMPLE_KR = 20
```

(Ordering note: Task 5's guard run should execute AFTER this change so the
re-validation also benefits from the larger sample — execute Tasks 6 → 5 → 7
if running sequentially; the task numbering here groups by theme.)

- [ ] **Step 2: Full suite**

Run: `.venv/bin/pytest tests/ -q` — green (no test pins VAL_SAMPLE_US; if one does, update it deliberately and say so in the commit).

- [ ] **Step 3: Commit**

```bash
git add config/settings.py
git commit -m "feat(validation): expand US gating sample 80->160 (owner-approved 2026-07-07)"
```

---

### Task 7: pullback v2 — optional distribution-veto entry condition

**Files:**
- Modify: `src/analysis/strategy_pullback.py`
- Test: `tests/test_strategies.py` (append)

**Interfaces:**
- Consumes: `distribution_evidence(df, recent_bars=N)` from Task 1.
- Produces: optional YAML param `dist_veto_bars` (int). ABSENT ⇒ byte-identical baseline (parity test). Present ⇒ extra condition "최근 N봉 내 분산(UTAD) 징후 없음" in `conditions()` (and therefore `evaluate()`, per the checklist invariant).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_strategies.py`:

```python
class TestPullbackDistVeto:
    """Part 2b (2026-07-07): optional distribution veto — parity when absent."""

    def _config(self, veto: int | None) -> dict:
        import copy

        from src.analysis.base_strategy import load_strategy_config

        cfg = copy.deepcopy(load_strategy_config())
        cfg["strategies"]["pullback"]["params"].pop("dist_veto_bars", None)
        if veto is not None:
            cfg["strategies"]["pullback"]["params"]["dist_veto_bars"] = veto
        return cfg

    def test_parity_without_param(self) -> None:
        from src.analysis.indicators import compute_indicators
        from src.analysis.strategy_pullback import PullbackStrategy
        from tests.test_distribution import utad_frame

        df = compute_indicators(utad_frame())
        conds = PullbackStrategy(self._config(None)).conditions(df)
        assert len(conds) == 6  # exact baseline checklist, no veto row

    def test_veto_condition_appended_and_fails_on_utad(self) -> None:
        from src.analysis.indicators import compute_indicators
        from src.analysis.strategy_pullback import PullbackStrategy
        from tests.test_distribution import utad_frame

        df = compute_indicators(utad_frame())
        conds = PullbackStrategy(self._config(10)).conditions(df)
        assert len(conds) == 7
        label, ok = conds[-1]
        assert "분산" in label
        assert ok is False  # fixture has a fresh UTAD -> veto trips

    def test_veto_passes_on_plain_uptrend(self) -> None:
        from src.analysis.indicators import compute_indicators
        from src.analysis.strategy_pullback import PullbackStrategy
        from tests.test_wyckoff_vpa import make_df

        df = compute_indicators(make_df([100 + 0.2 * i for i in range(200)]))
        label, ok = PullbackStrategy(self._config(10)).conditions(df)[-1]
        assert ok is True
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_strategies.py -v -k DistVeto`
Expected: `test_parity_without_param` PASSES (6 conditions today); the other two FAIL (only 6 conditions returned).

- [ ] **Step 3: Implement** in `src/analysis/strategy_pullback.py` — add import at top:

```python
from src.risk.distribution import distribution_evidence
```

Append to `conditions()` return-building (convert the current single `return [...]` into `conds = [...]` then):

```python
        if "dist_veto_bars" in p:
            n = int(p["dist_veto_bars"])
            conds.append((
                f"최근 {n}봉 내 분산(UTAD) 징후 없음",
                distribution_evidence(df, recent_bars=n) is None,
            ))
        return conds
```

(Compute note: VPA detection per bar-prefix makes backtests slower; wyckoff_spring
validation already pays the same cost and completes — accept, sequential as ever.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_strategies.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/pytest tests/ -q` — green.

```bash
git add src/analysis/strategy_pullback.py tests/test_strategies.py
git commit -m "feat(strategy): optional distribution-veto condition for pullback (dist_veto_bars)"
```

---

### Task 8: Part 2 validation runs + honest YAML verdicts (procedure)

Heavy compute — run overnight locally (sequential, 43MB store, fine on 8GB) or
via the Actions `workflow_dispatch` fallback if the laptop is needed. Each run's
verbatim output is REQUIRED in the spec log.

**Files:**
- Create: `tests/compare_pullback_veto.py`
- Modify (conditional): `config/strategies.yaml` (`enabled` / params, passers only)
- Modify: spec execution log

- [ ] **Step 1: Re-validate zscore_meanrev on the expanded sample**

Run: `.venv/bin/python main.py backtest --strategy zscore_meanrev 2>&1 | tee /tmp/val_zscore.txt`
Decision: enable in YAML ONLY if every gate passes AND OoS n ≥ 20. Update the
YAML comment block with the new verdict either way (mirror the existing comment style).

- [ ] **Step 2: Re-validate wyckoff_spring on the expanded sample**

Run: `.venv/bin/python main.py backtest --strategy wyckoff_spring 2>&1 | tee /tmp/val_spring.txt`
Same decision rule. Honest expectation: PF 0.73 baseline may fail on content, not just sample — report as-is.

- [ ] **Step 3: Create `tests/compare_pullback_veto.py`** — pre-registered veto grid N ∈ {5, 10} vs baseline (small grid per spec, anti-overfit), `compare_breakout_guards.py` pattern:

```python
"""Part 2b (2026-07-07): pullback baseline vs distribution-veto variants.

Pre-registered grid: dist_veto_bars in {5, 10} — fixed BEFORE results.
Selection is informational only; pullback is DISABLED and any enablement
requires the FULL Phase-4 gates (main.py backtest --strategy pullback with
the chosen param in YAML-candidate form). Survivorship bias applies.

Invoked via: .venv/bin/python tests/compare_pullback_veto.py
"""

import copy
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from config import settings
from src.analysis.base_strategy import load_strategy_config
from src.analysis.strategy_pullback import PullbackStrategy
from src.backtest.backtester import generate_entry_plan
from src.backtest.run_validation import build_frames
from src.backtest.validation import _collect_trades, aggregate_stats

logging.basicConfig(level=logging.WARNING)

GRID = [None, 5, 10]  # None = baseline


def main() -> None:  # noqa: D103
    frames = build_frames("us", settings.VAL_SAMPLE_US)
    market_of = {t: "us" for t in frames}
    all_dates = sorted({d for df in frames.values() for d in pd.to_datetime(df["date"]).dt.date})
    lo, hi = all_dates[0], all_dates[-1]
    split = all_dates[int(len(all_dates) * settings.VAL_IS_FRAC)]
    print(f"pullback veto grid — US sample {len(frames)} · 생존 편향 주의, 과거 성과")
    print(f"{'variant':<22}{'OoS n':>8}{'OoS WR':>9}{'OoS PF':>9}{'IS PF':>8}")
    for veto in GRID:
        config = copy.deepcopy(load_strategy_config())
        config["strategies"]["pullback"]["params"].pop("dist_veto_bars", None)
        if veto is not None:
            config["strategies"]["pullback"]["params"]["dist_veto_bars"] = veto
        strategy = PullbackStrategy(config)
        plans = {t: generate_entry_plan(df, strategy, t, market_of[t]) for t, df in frames.items()}
        oos = aggregate_stats(_collect_trades(frames, plans, strategy, market_of, split, hi))
        ins = aggregate_stats(_collect_trades(frames, plans, strategy, market_of, lo, split))
        name = "baseline" if veto is None else f"dist_veto_bars={veto}"
        print(
            f"{name:<22}{oos['n']:>8}{oos['win_rate'] * 100:>8.1f}%"
            f"{oos['profit_factor']:>9.2f}{ins['profit_factor']:>8.2f}"
        )


if __name__ == "__main__":
    main()
```

(Stat keys `n` / `win_rate` (fraction 0–1) / `profit_factor` verified against
`aggregate_stats` usage in `tests/compare_breakout_guards.py`.)

- [ ] **Step 4: Run the veto grid, capture output**

Run: `.venv/bin/python tests/compare_pullback_veto.py 2>&1 | tee /tmp/val_pullback_veto.txt`
Decision: if a veto variant clearly improves OoS PF toward ≥1 territory, run
`main.py backtest --strategy pullback` with that param set as a YAML-candidate
(temporary local edit) for the full gates; enable ONLY on full PASS. Otherwise
pullback stays disabled — record honestly.

- [ ] **Step 5: Record all verdicts**

Append to the spec execution log (`### Part 2 — 확대 표본 재검증`), one table +
the three verbatim outputs untrimmed. Update each strategy's YAML comment block
with the 07-07 verdict (enabled or not). Confirm active-strategy count ≤ 7.

- [ ] **Step 6: Full suite + final commit**

Run: `.venv/bin/pytest tests/ -q` — green.

```bash
git add tests/compare_pullback_veto.py config/strategies.yaml docs/superpowers/specs/2026-07-07-entry-diversification-design.md
git commit -m "feat(validation): expanded-sample Phase-4 verdicts for zscore/spring/pullback-veto"
```

---

## Execution-order note

Thematic order above; the efficient RUN order is **1 → 2 → 3 → 4 → 6 → 7 → 5 → 8**
(sample expansion before the heavy validation runs so nothing runs twice).
Tasks 5 and 8 are compute-bound procedures (hours) — everything else is
minutes.
