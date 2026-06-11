"""Parquet + DuckDB market-data store, partitioned by market/year.

Layout: DATA_ROOT/{market}/{year}.parquet (long format, zstd-compressed).
Canonical columns: ticker, date, open, high, low, close, volume, source.

The store is published to the orphan `data` branch as a SINGLE squashed
commit (force-push, no history) — see publish_to_data_branch().
"""

import logging
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

CANONICAL_COLUMNS = ["ticker", "date", "open", "high", "low", "close", "volume", "source"]


class ParquetStore:
    """Market-data store over per-market, per-year Parquet files."""

    def __init__(self, root: Path | None = None) -> None:
        """Initialize the store.

        Args:
            root: Data directory root. Defaults to settings.DATA_ROOT.
        """
        self.root = root or settings.DATA_ROOT

    def _market_dir(self, market: str) -> Path:
        return self.root / market.lower()

    def upsert(self, df: pd.DataFrame, market: str) -> int:
        """Merge new OHLCV rows into the store, deduplicating on (ticker, date).

        Newer rows win on conflict. Files are rewritten per affected year only.

        Args:
            df: Long-format frame with CANONICAL_COLUMNS.
            market: Market key, e.g. "us" or "kr".

        Returns:
            Total number of rows now stored in the affected year partitions.
        """
        missing = set(CANONICAL_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"upsert frame missing columns: {sorted(missing)}")
        frame = df[CANONICAL_COLUMNS].copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        market_dir = self._market_dir(market)
        market_dir.mkdir(parents=True, exist_ok=True)

        total_rows = 0
        for year, year_df in frame.groupby(frame["date"].map(lambda d: d.year)):
            path = market_dir / f"{year}.parquet"
            if path.exists():
                existing = pd.read_parquet(path)
                merged = pd.concat([existing, year_df], ignore_index=True)
            else:
                merged = year_df
            merged = (
                merged.drop_duplicates(subset=["ticker", "date"], keep="last")
                .sort_values(["ticker", "date"])
                .reset_index(drop=True)
            )
            merged.to_parquet(path, compression="zstd", index=False)
            total_rows += len(merged)
            logger.info("store: %s/%s.parquet now %d rows", market, year, len(merged))
        return total_rows

    def load(
        self,
        market: str,
        tickers: list[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Query stored OHLCV via DuckDB over the Parquet partitions.

        Args:
            market: Market key, e.g. "us" or "kr".
            tickers: Optional ticker filter.
            start: Optional inclusive start date.
            end: Optional inclusive end date.

        Returns:
            Long-format frame sorted by (ticker, date); empty frame if no data.
        """
        glob = str(self._market_dir(market) / "*.parquet")
        if not list(self._market_dir(market).glob("*.parquet")):
            return pd.DataFrame(columns=CANONICAL_COLUMNS)
        conditions, params = [], []
        if tickers:
            conditions.append(f"ticker IN ({','.join('?' * len(tickers))})")
            params.extend(tickers)
        if start:
            conditions.append("date >= ?")
            params.append(start)
        if end:
            conditions.append("date <= ?")
            params.append(end)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM read_parquet('{glob}') {where} ORDER BY ticker, date"
        with duckdb.connect() as con:
            return con.execute(query, params).df()

    def last_date(self, market: str, ticker: str) -> date | None:
        """Return the most recent stored date for a ticker, or None."""
        df = self.load(market, tickers=[ticker])
        if df.empty:
            return None
        return pd.to_datetime(df["date"]).max().date()


def restore_from_data_branch(store_root: Path | None = None) -> bool:
    """Restore the persisted store from the orphan `data` branch into DATA_ROOT.

    MUST run before any scan on a fresh checkout (Actions runner): the branch
    is the long-term archive, and publish_to_data_branch() force-pushes the
    LOCAL store — without restoring first, accumulated history (3y+ retention)
    would be clobbered by a single day's fetch window.

    Local files are not overwritten when present-and-newer is irrelevant:
    parquet years are whole files, and the subsequent upsert() merges anyway.

    Returns:
        True if the branch existed and was restored; False when absent (first
        run) — callers proceed with an empty store.
    """
    from src.data.git_remote import authenticated_remote_url

    root = store_root or settings.DATA_ROOT
    remote_url = authenticated_remote_url(settings.REPO_ROOT)
    with tempfile.TemporaryDirectory(prefix="data-restore-") as tmp:
        clone = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", settings.DATA_BRANCH, remote_url, tmp],
            capture_output=True, text=True,
        )
        if clone.returncode != 0:
            logger.warning("data branch absent or unreachable — starting with empty store")
            return False
        copied = 0
        for src in Path(tmp).rglob("*"):
            if src.is_file() and src.suffix in (".parquet", ".json"):
                dest = root / src.relative_to(tmp)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                copied += 1
    logger.info("data branch restored: %d files into %s", copied, root)
    return True


def publish_to_data_branch(store_root: Path | None = None) -> None:
    """Publish DATA_ROOT to the orphan `data` branch as one squashed commit.

    Creates a fresh orphan commit containing only the data directory contents
    and force-pushes it, keeping the branch at exactly one commit (no history)
    to avoid repo bloat. Caller workflows must hold the `data-storage-branch`
    concurrency group.
    """
    root = store_root or settings.DATA_ROOT
    if not root.exists() or not any(root.rglob("*.parquet")):
        raise FileNotFoundError(f"no parquet data under {root}; nothing to publish")
    from src.data.git_remote import authenticated_remote_url

    repo_root = settings.REPO_ROOT
    remote_url = authenticated_remote_url(repo_root)

    with tempfile.TemporaryDirectory(prefix="data-branch-") as tmp:
        tmp_path = Path(tmp)
        for pattern in ("*.parquet", "*.json"):  # market data + breaker/state files
            for src in root.rglob(pattern):
                dest = tmp_path / src.relative_to(root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        (tmp_path / "README.md").write_text(
            "# data branch\n\nSingle squashed commit of market data (Parquet). "
            "Force-pushed by the pipeline; do not commit here manually.\n"
        )

        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

        git("init", "--initial-branch", settings.DATA_BRANCH)
        git("config", "user.email", "pipeline@swing-trader")
        git("config", "user.name", "swing-trader pipeline")
        git("add", "-A")
        git("commit", "-m", "data snapshot (squashed)")
        git("remote", "add", "origin", remote_url)
        git("push", "--force", "origin", settings.DATA_BRANCH)
    logger.info("data branch published (squashed force-push) to %s", remote_url)
