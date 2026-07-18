# swing-trader

Fully serverless, zero-cost swing trading analysis pipeline.
GitHub Actions (cron) + GitHub Pages (reports) + Telegram (alerts) + Cloudflare Worker (commands).
**The system recommends; the human decides.** Long-only, holding 3–20 days. US market is PRIMARY, KR secondary.

## Build / test commands

```bash
# Environment (Python 3.12 via Homebrew, venv mandatory — no global installs)
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Tests (always run before committing)
.venv/bin/pytest tests/ -q

# Local pipeline runs (--no-publish skips branch pushes)
.venv/bin/python main.py scan-us --no-publish
.venv/bin/python main.py analyze AAPL --no-publish
.venv/bin/python main.py backtest [--smoke]
```

## Key invariants (do not break)

- **Scan/backtest single source**: backtester generates entries by calling the
  SAME strategy.evaluate() per bar prefix; strategy thresholds live ONLY in
  config/strategies.yaml. conditions() is the checklist evaluate() consumes.
- **Exit parity**: live position monitoring and backtests both go through
  src/risk/exit_engine.check_exit() + strategy.should_exit().
- **Restore before publish**: any data-branch writer must call
  restore_from_data_branch() first — fresh runner checkouts would otherwise
  clobber the long-term archive (force-push semantics).
- **No forward-fill** of market data, ever. Short history -> NaN -> excluded.
- **Health check every scan** (zero signals included); gap guard is the ONLY
  silent-when-empty job.
- **Telegram top-5 rule**: scan message bodies carry at most 5 signal cards.
- **MC gate sizing**: Monte Carlo uses 10% equity per trade
  (settings.VAL_MC_TRADE_FRACTION, owner-approved 2026-06-12).
- **Wyckoff VPA (U2/U3)**: src/analysis/wyckoff_vpa.py is pure + repaint-free
  (pivots confirmed after pivot_strength right candles); params live under
  strategies.yaml wyckoff_spring.params.vpa; the distribution monitor
  (src/risk/distribution.py) runs on HELD tickers regardless of enablement.
- **Observe lane (2026-07-18)**: strategies.yaml `observe: true` runs a
  DISABLED strategy in scans as reference-only — separate 관찰 Telegram section
  (max OBSERVE_MAX_ITEMS, "추천 아님" labeled), reports + tracker rows included,
  but NEVER recommendation cards/top-5, send cutoffs, paper buys, the feed, or
  Lever-3 cutoff stats (propose_and_apply enabled_ids filter). `enabled: true`
  still requires Phase-4 PASS; observe is not a backdoor around the gate.
- **Charts (U5)**: lightweight-charts v5 via settings.CHART_BACKEND; Plotly
  renderer retained — set CHART_BACKEND="plotly" to roll back. All chart data
  is computed in Python and embedded as JSON; template JS only renders.
- **AI bridge (U6)**: manual copy ONLY — never auto-call an LLM API, never
  include positions in report content.
- **Trailing persistence (U7)**: confirmed scans update highest_close /
  current_trailing_sl in positions.yaml via update_trailing_state();
  preliminary (midday) scans must NOT touch it (in-progress bars); workflows
  commit positions.yaml only when the file actually changed.
- **Slots (U7)**: settings.MAX_POSITION_SLOTS drives 보유 카드 헤더와 슬롯
  가득 태그 — advisory only, never blocks signals.

## Dependency lock notes (Phase 1, 2026-06-11)

- **pandas-ta 0.4.71b0** (maintained line). The old 0.3.14b0 is gone from PyPI; 0.4.x
  requires Python >= 3.12 and numpy >= 2. The historical `numpy<2.0` landmine
  (`np.NaN` removal) is fixed in 0.4.x, so the stack runs on **numpy 2.2.6 / pandas 2.3.3**.
- **backtesting 0.6.5** verified to execute (not just import) against this set.
- Exact pins frozen in `requirements.txt` (full `pip freeze`). Do not upgrade casually;
  re-run both Phase 1 verification scripts after any dependency change.
- pykrx 1.2.8 prints a KRX login warning when `KRX_ID`/`KRX_PW` env vars are unset —
  investigate impact in Phase 2.

## Strategy interface contract

- Every strategy implements `BaseStrategy` (src/analysis/base_strategy.py):
  input = per-ticker OHLCV DataFrame + precomputed indicators; output = `Signal | None`.
- Each strategy also provides a `backtesting.py`-compatible class sharing the **same YAML
  parameters** from `config/strategies.yaml` — never duplicate thresholds in code.
- Strategies self-register via decorator (src/analysis/registry.py); no hardcoded lists.

## Activation rule & 7-cap

- `enabled: true` in `config/strategies.yaml` ONLY after passing all Phase-4 validation
  gates (IS/OoS, walk-forward, Monte Carlo >= 1,000, sensitivity +-20%, regime-sliced,
  benchmark, strict pass criteria). Borderline = disabled, stated honestly.
- **Hard cap: max 7 strategies enabled simultaneously.** (The confluence merge
  layer was removed in upgrade U1/A-4; the cap itself remains.)
- **Send cutoffs (U1/A-2)** are separate from ranking: settings MIN_PROFIT_FACTOR_SEND /
  MIN_SAMPLE_SEND / MIN_STRENGTH_SEND / MAX_STOP_LOSS_PCT gate the Telegram message
  only; reports are still generated and the health check shows the excluded count.
- **52-week gauge (U1/A-1)** is ALWAYS computed from our own adjusted series;
  external 52w fields render only within FUND_52W_DEVIATION_MAX_PCT of own data.

## Adaptive loop (semi-auto; Lever 1 active, L2–L4 deferred)

- `ADAPTIVE_LOOP_ENABLED` master flag — **False = byte-for-byte baseline**
  (legacy single-condition circuit breaker; no hardening/hysteresis/safeguard).
- The loop NEVER predicts price (no ML/RL — does not violate §14). It only
  SUPPRESSES negative-expectancy strategies using already-realized +10d forward
  returns from the tracker. Past frequency ≠ future probability — it cannot
  guarantee returns; every adaptive Telegram notice repeats this disclaimer.
- **Lever 1 — circuit-breaker hardening (weekly, AUTO):** suspend requires
  `mean +10d < CB_SUSPEND_RET_THRESHOLD AND win_rate < CB_SUSPEND_WINRATE_FLOOR`
  (the spec's `OR PF<1` is vacuous: mean<0 ⟺ PF<1, so a low win rate is the real
  corroboration that avoids suspending on one unlucky window; PF is shown for
  context). Reactivate only when `mean +10d ≥ CB_REACTIVATE_RET_THRESHOLD`
  (hysteresis — a higher bar than suspend, prevents flapping). **Single-strategy-
  silence safeguard:** if every ENABLED strategy would suspend, the best one is
  kept active so the system never goes fully mute. Suspension is runtime muting
  (`is_suspended` at scan time), NOT an `enabled` flag change.
- **Lever 3 — adaptive acceptance cutoff (weekly, AUTO):** adapts the EXISTING
  send cutoff (`MIN_STRENGTH_SEND`) — NOT a parallel one. `effective_cutoff()`
  (used by send_filter) returns the adaptive value or, when the loop is off,
  `MIN_STRENGTH_SEND` (baseline). Nudged ≤ `ACCEPTANCE_CUTOFF_MAX_STEP`/run,
  clamped to [FLOOR, CEILING]; raises when the just-accepted band loses money,
  lowers only when the just-rejected band clearly outperforms (so it can't
  ratchet to the ceiling). State: `data/state/acceptance_cutoff.json`. Applied
  changes are audited to `data/state/adaptive_audit.json` (JSON array — NOT
  .jsonl, so it rides the data-branch glob).
- **L2 (regime weighting) / L4 (approval-gated threshold re-opt) are DEFERRED** —
  the live realized sample is still too thin to validate them (they would be
  perpetually "표본 부족"). Do not build/enable without a data-sufficiency review.

## Holdings auto-report + US news (add-on)

- At each CONFIRMED close (kr-close / us-close, NOT the preliminary midday scan),
  every position in positions.yaml gets a `/analyze`-equivalent HTML report via
  the SHARED `analyze_cmd.build_analysis_report()` (single source — `/analyze`
  and holdings call the same builder). The report is a NEUTRAL analysis with NO
  position data (entry/qty/P&L stay in private Telegram only — §2 rule #4). The
  held loop reuses the already-computed indicator frame (no re-fetch); the single
  `publish_reports()` runs AFTER the held loop so signal + holdings reports ship
  together. Flags: `HOLDINGS_REPORT_ENABLED`, `HOLDINGS_NEWS_ENABLED` (both off =
  baseline).
- US holdings ONLY also get news (headlines + links) via `src/data/news.py`
  (`fetch_us_news`, yfinance `.news`, best-effort — any failure returns [], never
  blocks a scan; handles both the nested-`content` and old top-level schemas). KR
  news is out of scope (unreliable coverage). The Telegram holdings block adds the
  report link + (US) up to `HOLDINGS_NEWS_MAX_ITEMS` headlines.

## Cron <-> KST map (Cloudflare Worker cron -> repository_dispatch, UTC)

| Workflow | KST | UTC cron | repository_dispatch type |
|---|---|---|---|
| kr-midday.yml | 평일 12:37 | `37 3 * * 1-5` | `cron-kr-midday` |
| kr-close.yml | 평일 15:47 | `47 6 * * 1-5` | `cron-kr-close` |
| us-close.yml | 화–토 07:07 | `7 22 * * 1-5` | `cron-us-close` |
| us-premarket.yml | 평일 16:37 | `37 7 * * 1-5` | `cron-us-premarket` |
| weekly.yml | 일 04:07 | `7 19 * * 6` | `cron-weekly` |

**Scheduling lives in the Cloudflare Worker, not GitHub.** GitHub-native
`schedule:` triggers lagged multiple hours on the free tier (lowest priority),
so they were retired. The crons above now live in `worker/wrangler.toml`
`[triggers]`; the Worker's `scheduled()` handler maps each cron -> a
`repository_dispatch` event_type (CRON_EVENTS in worker.js) -> the matching
workflow, which runs promptly (same punctual path as the Telegram `/commands`).
**The wrangler.toml crons and worker.js CRON_EVENTS must stay in sync.** Each
workflow listens on its own `repository_dispatch` type (only the right one
fires) and keeps `workflow_dispatch:` for manual/fallback runs. If a dispatch
fails, the Worker DMs the owner on Telegram (the safety net for missed runs).
The +7-min offsets are vestigial now (no GitHub-cron congestion to dodge) but
kept so the KST wall-clock times are unchanged.

## Data-branch convention

- Market data = Parquet (partitioned by market/year), queried via DuckDB, committed to the
  orphan `data` branch as a **single squashed commit (force-push, no history)**.
- Long-term retention (3+ years); no auto-deletion.
- Every workflow that writes the `data` branch or `positions.yaml` declares
  `concurrency: { group: data-storage-branch, cancel-in-progress: false }`.

## Reporting-integrity rules

- Attach verbatim execution output to every Phase report; never trim away failures.
- Never call unexecuted code "verified". State executed vs. untested explicitly.
- Backtest results are historical; never imply guaranteed future returns.
- Survivorship bias disclosure is mandatory in validation reports and README.
- Reports NEVER contain owner positions/entry prices/quantities.

## Language rules

- User-facing text (Telegram, HTML reports, README): **Korean**.
- Code, comments, docstrings, logs: **English**.
- `logging` only (no `print` in src/); 100% type hints; Google-style docstrings;
  magic numbers live in config YAML; secrets via GitHub Secrets / `.env` only.

## Dev-machine memory rules (MacBook Air 8GB)

- Process tickers sequentially, one in memory at a time; no multiprocessing locally.
- Parameter grids <= 1,000 combos per chunk. Heavy full-universe runs go to Actions.
