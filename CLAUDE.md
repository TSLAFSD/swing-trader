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

## Cron <-> KST map (GitHub Actions, UTC)

| Workflow | KST | UTC cron |
|---|---|---|
| kr-midday.yml | 평일 12:30 | `30 3 * * 1-5` |
| kr-close.yml | 평일 15:40 | `40 6 * * 1-5` |
| us-close.yml | 화–토 07:00 | `0 22 * * 1-5` |
| us-premarket.yml | 평일 16:30 | `30 7 * * 1-5` |
| weekly.yml | 일 04:00 | `0 19 * * 6` |

Actions cron can lag 15–30 min at busy times; the 12:30 preliminary scan tolerates this.

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
