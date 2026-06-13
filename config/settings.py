"""Central configuration: paths, universe filters, data-pipeline thresholds.

Strategy-specific parameters live in config/strategies.yaml (Phase 3+).
Secrets come from environment variables / GitHub Secrets only.
"""

import os
from pathlib import Path

# --- Paths -------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"  # gitignored on main; lives on orphan `data` branch
CACHE_DIR = REPO_ROOT / "config" / "cache"  # committed fallback caches (e.g. Russell 1000)

# --- Data branch -------------------------------------------------------
DATA_BRANCH = "data"
DATA_BRANCH_REMOTE = "origin"

# --- Universe: US ------------------------------------------------------
ISHARES_IWB_CSV_URL = (
    "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IWB_holdings&dataType=fund"
)
RUSSELL1000_WIKI_URL = "https://en.wikipedia.org/wiki/Russell_1000_Index"
RUSSELL1000_CACHE_FILE = CACHE_DIR / "russell1000.csv"
US_MIN_PRICE = 5.0  # USD
US_MIN_AVG_DOLLAR_VOLUME = 5_000_000.0  # 20-day avg daily trading value, USD

# --- Universe: KR ------------------------------------------------------
KR_MIN_PRICE = 1_000.0  # KRW
KR_MIN_AVG_TRADING_VALUE = 1_000_000_000.0  # 20-day avg daily trading value, KRW (10억)

# --- Fetchers ----------------------------------------------------------
US_BATCH_SIZE = 50
US_BATCH_SLEEP_SEC = 2.0
KR_FETCH_TIMEOUT_SEC = 10.0  # per spec: FDR timeout >= 10s
KR_RETRY_ATTEMPTS = 3
KR_RETRY_BACKOFF_BASE_SEC = 1.0  # exponential: 1s, 2s, 4s
HISTORY_YEARS = 3  # default depth for initial fetch / backtests

# --- Data quality ------------------------------------------------------
ANOMALY_DAILY_MOVE_PCT = 30.0  # 1-day move beyond +-30% -> exclude from signals, flag

# --- Composite grade A/B/C (U4/Part D; report shows the same numbers) -----
# composite = strength*W_S + confidence*100*W_C + regime_score*W_R
# regime_score: no downgrade=100, one downgrade (index OR breadth)=50, both=0
GRADE_W_STRENGTH = 0.5
GRADE_W_CONFIDENCE = 0.3
GRADE_W_REGIME = 0.2
GRADE_A_MIN = 70.0
GRADE_B_MIN = 50.0

# Contrarian indicators counted on signal cards (full list in the report):
# ① close<SMA200 ② MACD hist<0 ③ RSI14>70 ④ volume<0.7xVolMA20
# ⑤ zscore>+1.5 ⑥ SMA60 slope down  (owner-approved 2026-06-12)

# --- Positions UX ---------------------------------------------------------
STOP_PROXIMITY_PCT = 3.0  # current price within +3% of stop -> ⚠️손절근접
MAX_POSITION_SLOTS = 5  # U7/G-2: 보유 카드 "n/5 슬롯", 만석 시 신규 시그널 태그

# --- Send cutoffs (U1/A-2: applied at the SEND stage, separate from rank) --
MIN_PROFIT_FACTOR_SEND = 1.0  # per-ticker confidence PF below this -> not sent
MIN_SAMPLE_SEND = 5  # confidence trades below this -> not sent; also hides Kelly
MIN_STRENGTH_SEND = 20.0  # final (confidence-adjusted) strength floor
MAX_STOP_LOSS_PCT = 15.0  # suggested stop wider than this from entry...
STOP_TOO_WIDE_MODE = "drop"  # ..."drop" = don't send | "tag" = send with warning
FUND_52W_DEVIATION_MAX_PCT = 5.0  # external 52w high/low vs own data gate (A-1)

# --- Signal-quality layers ----------------------------------------------
RS_PERCENTILE_FLOOR = 30.0  # BUY candidates below this momentum percentile...
RS_FLOOR_ACTION = "drop"  # ..."drop" or "downgrade" (x0.7 strength)
RS_DOWNGRADE_FACTOR = 0.7
EARNINGS_WARN_DAYS = 5  # trading days; best-effort tag, never blocks
SCAN_TOP_N = 10  # ranked signals kept per scan (Telegram shows top 5)

# --- Validation gates (Phase 4, spec §7 Layer 1) ------------------------
VAL_IS_FRAC = 0.70  # in-sample 70% / out-of-sample 30% time split
VAL_WF_WINDOWS = 3  # walk-forward rolling validate windows
VAL_WF_MIN_PASS = 2  # PF > 1.0 required in >= this many windows
VAL_MC_RUNS = 1000  # Monte Carlo trade-resampling paths
VAL_MC_MDD_MAX_PCT = 35.0  # 5th-percentile (worst-tail) MDD bound
# Owner-approved 2026-06-12: MC models realistic sizing (10% of equity per
# trade, matching multi-position usage + Kelly hints), not 100% rotation.
VAL_MC_TRADE_FRACTION = 0.10
VAL_SENS_PERTURB = 0.20  # +-20% parameter perturbation
VAL_SENS_PF_RATIO_MIN = 0.6  # perturbed PF >= ratio x base PF...
VAL_SENS_PF_ABS_MIN = 0.9  # ...AND >= this absolute floor (cliff-edge = overfit)
VAL_MIN_TRADES_OOS = 20  # below this the OoS verdict is statistically meaningless
VAL_WR_DROP_MAX = 0.10  # OoS win rate >= IS win rate - 10%p
VAL_SAMPLE_US = 80  # representative universe sample sizes
VAL_SAMPLE_KR = 20
VAL_SENS_TICKERS = 20  # sensitivity runs use a sub-sample (compute budget)

# --- Per-ticker confidence (Layer 2) ------------------------------------
CONF_MIN_TRADES = 10  # below: capped + "표본 부족 — 신뢰 불가"
CONF_CAP_LOW_SAMPLE = 0.3

# --- Circuit breaker (spec §5.3) -----------------------------------------
CB_TRAILING_SIGNALS = 20  # trailing window size
CB_MEAN_FWD10_MIN = -0.02  # suspend when mean +10d forward return < -2%

# --- Reports / GitHub Pages ---------------------------------------------
REPORTS_BRANCH = "gh-pages"
PAGES_BASE_URL = "https://tslafsd.github.io/swing-trader"
REPORT_CHART_MONTHS = 6
# U5 (owner-approved spec revision): TradingView lightweight-charts v5.
# "plotly" rolls back to the retained fallback renderer.
CHART_BACKEND = "lightweight"
LW_CHARTS_CDN = "https://unpkg.com/lightweight-charts@5/dist/lightweight-charts.standalone.production.js"

# --- Gap Guard (us-premarket, spec §11.1) --------------------------------
GAP_ALERT_PCT = 3.0

# --- /analyze diagnostic ---------------------------------------------------
# Reference (참고) stop shown in the deep-analysis report: current price minus
# k*ATR(14) — the level an ATR-trailing exit would start at. Matches the
# chandelier convention (atr_k=3.0) used by the trailing strategies. /analyze
# fires no strategy, so this is an informational anchor, never a live stop.
ANALYZE_REF_ATR_K = 3.0

# --- Positions ------------------------------------------------------------
POSITIONS_FILE = REPO_ROOT / "config" / "positions.yaml"
REBUY_COOLDOWN_DAYS = 0  # 0 = off; >0 blocks re-signals for N days after /remove
POSITION_DEFAULT_STOP_PCT = 5.0  # /add default stop (editable in positions.yaml)
POSITION_DEFAULT_TARGET_PCT = 15.0  # /add default target

# --- Paper portfolio (가상 매매: forward out-of-sample 성적표; P-A) ---------
# A virtual portfolio that buys fresh A-grade signals at the confirmed close
# and exits via the SAME engine the live monitor uses (parity). Distinct from
# owner positions (positions.yaml) and from the flat signals.parquet study.
PAPER_ENABLED = True  # run the virtual portfolio on confirmed scans
PAPER_START_EQUITY = 10_000.0  # virtual base capital (abstract notional units)
PAPER_TRADE_FRACTION = 0.20  # notional per trade = START_EQUITY * this (5 slots = 100%)
PAPER_GRADES = ("A",)  # only these composite grades enter the paper portfolio
PAPER_SLIPPAGE_BPS = 5.0  # one-way slippage, basis points (entry pays more, exit less)
PAPER_FEE_BPS = 0.0  # commission per side, basis points (0 = none)
PAPER_DIR = DATA_ROOT / "paper"  # rides the orphan `data` branch (parquet + json glob)
PAPER_TRADES_FILE = PAPER_DIR / "trades.parquet"  # append-only closed-trade ledger
PAPER_OPEN_FILE = PAPER_DIR / "open.json"  # mutable open-position state (JSON, not YAML)
PAPER_SCHEMA_VERSION = 1
# P-C feedback loop (read-only "what worked"; suggestions are manual-apply only).
PAPER_FEEDBACK_MIN_SAMPLE = 10  # min rows before a feedback suggestion is trusted
PAPER_FEEDBACK_FILE = PAPER_DIR / "feedback.json"  # machine-readable findings (Claude/P-C)

# --- Telegram (send-only; secrets via env) -----------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
