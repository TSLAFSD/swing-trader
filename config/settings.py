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

# --- Gap Guard (us-premarket, spec §11.1) --------------------------------
GAP_ALERT_PCT = 3.0

# --- Positions ------------------------------------------------------------
POSITIONS_FILE = REPO_ROOT / "config" / "positions.yaml"
REBUY_COOLDOWN_DAYS = 0  # 0 = off (Phase 6 wires the cooldown check)

# --- Telegram (send-only; secrets via env) -----------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
