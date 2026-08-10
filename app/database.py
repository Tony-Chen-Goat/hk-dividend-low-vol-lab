from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Mapping

import pandas as pd

from .config import DEFAULT_DB_PATH


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS security_master (
  symbol TEXT PRIMARY KEY, raw_symbol TEXT, name TEXT, sector TEXT,
  listing_date TEXT, security_type TEXT, board TEXT, index_membership TEXT,
  effective_date TEXT, end_date TEXT, source TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS daily_prices (
  symbol TEXT NOT NULL, trade_date TEXT NOT NULL, open REAL, high REAL, low REAL,
  close REAL, adjusted_close REAL, volume REAL, traded_value REAL,
  source TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (symbol, trade_date)
);
CREATE TABLE IF NOT EXISTS dividends (
  symbol TEXT NOT NULL, ex_date TEXT NOT NULL, payment_date TEXT,
  dividend_per_share REAL, currency TEXT, source TEXT NOT NULL,
  PRIMARY KEY (symbol, ex_date)
);
CREATE TABLE IF NOT EXISTS corporate_actions (
  symbol TEXT NOT NULL, action_date TEXT NOT NULL, action_type TEXT NOT NULL,
  value REAL, source TEXT NOT NULL,
  PRIMARY KEY (symbol, action_date, action_type)
);
CREATE TABLE IF NOT EXISTS fundamentals (
  symbol TEXT NOT NULL, report_period TEXT NOT NULL, published_date TEXT,
  net_income REAL, operating_cash_flow REAL, cash_dividends_paid REAL,
  shares_outstanding REAL, free_float_shares REAL, payout_ratio REAL,
  source TEXT, data_quality TEXT, PRIMARY KEY (symbol, report_period)
);
CREATE TABLE IF NOT EXISTS monthly_universe (
  month_end TEXT NOT NULL, symbol TEXT NOT NULL, included INTEGER NOT NULL,
  exclusion_reasons TEXT, source TEXT, PRIMARY KEY (month_end, symbol)
);
CREATE TABLE IF NOT EXISTS monthly_features (
  month_end TEXT NOT NULL, symbol TEXT NOT NULL, raw_json TEXT, winsorized_json TEXT,
  score_json TEXT, contribution_json TEXT, model_score REAL, coverage REAL,
  quality_flag TEXT, PRIMARY KEY (month_end, symbol)
);
CREATE TABLE IF NOT EXISTS forward_returns (
  month_end TEXT NOT NULL, symbol TEXT NOT NULL, next_month_end TEXT,
  forward_return REAL, PRIMARY KEY (month_end, symbol)
);
CREATE TABLE IF NOT EXISTS backtest_holdings (
  experiment_id TEXT NOT NULL, month_end TEXT NOT NULL, symbol TEXT NOT NULL,
  target_weight REAL, actual_return REAL, contribution REAL, sector TEXT,
  PRIMARY KEY (experiment_id, month_end, symbol)
);
CREATE TABLE IF NOT EXISTS experiments (
  experiment_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
  universe_name TEXT, data_start TEXT, data_end TEXT, train_window TEXT,
  validation_window TEXT, factor_weights_json TEXT, group_weights_json TEXT,
  portfolio_method TEXT, selected_count INTEGER, max_stock_weight REAL,
  max_sector_weight REAL, transaction_cost REAL, metrics_json TEXT,
  score REAL, coverage REAL, survivor_bias INTEGER, quality_note TEXT,
  is_out_of_sample INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS update_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
  requested_count INTEGER, success_count INTEGER, failed_count INTEGER,
  failures_json TEXT, status TEXT
);
"""


def connect(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database(path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def transaction(path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: Iterable[Mapping],
    *,
    preserve_existing_on_null: bool = False,
) -> int:
    rows = list(rows)
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ",".join("?" for _ in columns)
    if preserve_existing_on_null:
        assignments = ",".join(
            f"{column}=COALESCE(excluded.{column},{column})" for column in columns
        )
    else:
        assignments = ",".join(f"{column}=excluded.{column}" for column in columns)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) ON CONFLICT DO UPDATE SET {assignments}"
    conn.executemany(sql, [[_sql_value(row.get(column)) for column in columns] for row in rows])
    return len(rows)


def _sql_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def table_counts(path: str | Path = DEFAULT_DB_PATH) -> dict[str, int]:
    initialize_database(path)
    names = ["security_master", "daily_prices", "dividends", "fundamentals", "monthly_features", "experiments"]
    with connect(path) as conn:
        return {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names}


def read_table(table: str, path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    initialize_database(path)
    allowed = {"security_master", "daily_prices", "dividends", "corporate_actions", "fundamentals", "monthly_universe", "monthly_features", "forward_returns", "backtest_holdings", "experiments", "update_logs"}
    if table not in allowed:
        raise ValueError(f"不允许读取表: {table}")
    with connect(path) as conn:
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)


def export_table_csv(table: str, path: str | Path = DEFAULT_DB_PATH) -> bytes:
    return read_table(table, path).to_csv(index=False).encode("utf-8-sig")


def backup_database(destination: str | Path, path: str | Path = DEFAULT_DB_PATH) -> Path:
    initialize_database(path)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination


def restore_database(uploaded_bytes: bytes, path: str | Path = DEFAULT_DB_PATH) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".restore.tmp")
    temp.write_bytes(uploaded_bytes)
    try:
        with sqlite3.connect(temp) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"SQLite 完整性检查失败: {result}")
        temp.replace(target)
        initialize_database(target)
    finally:
        temp.unlink(missing_ok=True)
