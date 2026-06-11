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

# --- Telegram (send-only; secrets via env) -----------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
