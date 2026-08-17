from __future__ import annotations

import json
import shutil
import sqlite3
import re
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
  experiment_id TEXT NOT NULL, model_name TEXT NOT NULL DEFAULT 'full_13', month_end TEXT NOT NULL, symbol TEXT NOT NULL, raw_json TEXT, winsorized_json TEXT,
  score_json TEXT, contribution_json TEXT, model_score REAL, coverage REAL,
  quality_flag TEXT, next_month_end TEXT, forward_return REAL,
  PRIMARY KEY (experiment_id, month_end, symbol)
);
CREATE TABLE IF NOT EXISTS experiment_universe (
  experiment_id TEXT NOT NULL, month_end TEXT NOT NULL, symbol TEXT NOT NULL,
  included INTEGER NOT NULL, exclusion_reasons TEXT, source TEXT,
  PRIMARY KEY (experiment_id, month_end, symbol)
);
CREATE TABLE IF NOT EXISTS forward_returns (
  month_end TEXT NOT NULL, symbol TEXT NOT NULL, next_month_end TEXT,
  forward_return REAL, PRIMARY KEY (month_end, symbol)
);
CREATE TABLE IF NOT EXISTS backtest_holdings (
  experiment_id TEXT NOT NULL, month_end TEXT NOT NULL, symbol TEXT NOT NULL,
  target_weight REAL, raw_weight REAL, actual_return REAL, contribution REAL,
  sector TEXT, name TEXT, model_score REAL, factor_coverage REAL,
  cash_weight REAL, constraint_note TEXT, rebalance_action TEXT,
  PRIMARY KEY (experiment_id, month_end, symbol)
);
CREATE TABLE IF NOT EXISTS rank_ic_monthly (
  experiment_id TEXT NOT NULL, month_end TEXT NOT NULL, rank_ic REAL,
  valid_count INTEGER, skip_reason TEXT, cumulative_rank_ic REAL,
  rolling_12m_ic REAL, PRIMARY KEY (experiment_id, month_end)
);
CREATE TABLE IF NOT EXISTS experiment_factor_ic (
  experiment_id TEXT NOT NULL, factor TEXT NOT NULL, mean_rank_ic REAL,
  rank_ic_std REAL, positive_ratio REAL, rank_icir REAL,
  annualized_rank_icir REAL, latest_12m_rank_ic REAL,
  PRIMARY KEY (experiment_id, factor)
);
CREATE TABLE IF NOT EXISTS backtest_monthly (
  experiment_id TEXT NOT NULL, month_end TEXT NOT NULL, gross_return REAL,
  transaction_cost REAL, net_return REAL, turnover REAL, cash_weight REAL,
  selected_count INTEGER, entered_count INTEGER, exited_count INTEGER,
  entered_symbols TEXT, exited_symbols TEXT, retained_symbols TEXT,
  net_value REAL, gross_value REAL, drawdown REAL,
  PRIMARY KEY (experiment_id, month_end)
);
CREATE TABLE IF NOT EXISTS experiments (
  experiment_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
  version_name TEXT, experiment_note TEXT,
  model_name TEXT, universe_name TEXT, data_start TEXT, data_end TEXT, train_window TEXT,
  validation_window TEXT, factor_weights_json TEXT, group_weights_json TEXT,
  portfolio_method TEXT, selected_count INTEGER, max_stock_weight REAL,
  max_sector_weight REAL, transaction_cost REAL, metrics_json TEXT,
  score REAL, coverage REAL, survivor_bias INTEGER, quality_note TEXT,
  is_out_of_sample INTEGER NOT NULL DEFAULT 1, status TEXT DEFAULT 'features_ready',
  risk_settings_json TEXT, backtest_settings_json TEXT,
  approved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS research_settings (
  setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    # Streamlit may serve more than one browser session at the same time.  A
    # short default SQLite timeout can otherwise turn harmless concurrent
    # reads/batch writes into intermittent ``database is locked`` failures.
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def initialize_database(path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _migrate_schema(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    feature_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(monthly_features)").fetchall()
    }
    if "experiment_id" not in feature_columns:
        model_expression = "model_name" if "model_name" in feature_columns else "'full_13'"
        conn.executescript(
            f"""
            ALTER TABLE monthly_features RENAME TO monthly_features_legacy;
            CREATE TABLE monthly_features (
              experiment_id TEXT NOT NULL, model_name TEXT NOT NULL DEFAULT 'full_13',
              month_end TEXT NOT NULL, symbol TEXT NOT NULL,
              raw_json TEXT, winsorized_json TEXT, score_json TEXT,
              contribution_json TEXT, model_score REAL, coverage REAL,
              quality_flag TEXT, next_month_end TEXT, forward_return REAL,
              PRIMARY KEY (experiment_id, month_end, symbol)
            );
            INSERT INTO monthly_features (
              experiment_id, model_name, month_end, symbol, raw_json,
              winsorized_json, score_json, contribution_json, model_score,
              coverage, quality_flag, next_month_end, forward_return
            )
            SELECT
              'legacy-' || {model_expression}, {model_expression}, month_end,
              symbol, raw_json, winsorized_json, score_json, contribution_json,
              model_score, coverage, quality_flag, NULL, NULL
            FROM monthly_features_legacy;
            DROP TABLE monthly_features_legacy;
            """
        )
        legacy_models = conn.execute(
            "SELECT DISTINCT experiment_id, model_name FROM monthly_features"
        ).fetchall()
        legacy_experiments = [(str(experiment_id), str(model_name)) for experiment_id, model_name in legacy_models]
    else:
        legacy_experiments = []

    feature_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(monthly_features)").fetchall()
    }
    for column, definition in {
        "next_month_end": "TEXT", "forward_return": "REAL",
    }.items():
        if column not in feature_columns:
            conn.execute(f"ALTER TABLE monthly_features ADD COLUMN {column} {definition}")
    conn.execute(
        """
        UPDATE monthly_features
        SET next_month_end = COALESCE(
              next_month_end,
              (SELECT r.next_month_end FROM forward_returns r
               WHERE r.month_end = monthly_features.month_end
                 AND r.symbol = monthly_features.symbol)
            ),
            forward_return = COALESCE(
              forward_return,
              (SELECT r.forward_return FROM forward_returns r
               WHERE r.month_end = monthly_features.month_end
                 AND r.symbol = monthly_features.symbol)
            )
        WHERE forward_return IS NULL OR next_month_end IS NULL
        """
    )

    experiment_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()
    }
    if "model_name" not in experiment_columns:
        conn.execute("ALTER TABLE experiments ADD COLUMN model_name TEXT")
    experiment_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()
    }
    for column, definition in {
        "version_name": "TEXT", "experiment_note": "TEXT",
        "universe_name": "TEXT", "data_start": "TEXT", "data_end": "TEXT",
        "train_window": "TEXT", "validation_window": "TEXT",
        "portfolio_method": "TEXT", "selected_count": "INTEGER",
        "max_stock_weight": "REAL", "max_sector_weight": "REAL",
        "transaction_cost": "REAL", "score": "REAL", "coverage": "REAL",
        "status": "TEXT DEFAULT 'features_ready'",
        "risk_settings_json": "TEXT",
        "backtest_settings_json": "TEXT",
        "approved": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        if column not in experiment_columns:
            conn.execute(f"ALTER TABLE experiments ADD COLUMN {column} {definition}")
    conn.execute(
        "UPDATE experiments SET status = 'features_ready' "
        "WHERE status IS NULL OR TRIM(status) = ''"
    )
    conn.execute("UPDATE experiments SET approved = 0 WHERE approved IS NULL")
    conn.execute(
        "UPDATE experiments SET risk_settings_json = '{}' "
        "WHERE risk_settings_json IS NULL"
    )
    conn.execute(
        "UPDATE experiments SET backtest_settings_json = '{}' "
        "WHERE backtest_settings_json IS NULL"
    )
    _backfill_experiment_versions(conn)
    for experiment_id, model_name in legacy_experiments:
        conn.execute(
            """
            INSERT OR IGNORE INTO experiments (
              experiment_id, name, created_at, model_name, universe_name,
              factor_weights_json, group_weights_json, metrics_json,
              survivor_bias, quality_note, is_out_of_sample, status
            ) VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, '{}', '{}', '{}', 1, ?, 0, 'features_ready')
            """,
            (
                experiment_id,
                f"历史未版本化数据（{model_name}）",
                model_name,
                "历史导入证券池",
                "由旧版数据库迁移；未保存当时的完整权重和风险设置。",
            ),
        )

    _backfill_experiment_versions(conn)

    holding_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(backtest_holdings)").fetchall()
    }
    for column, definition in {
        "raw_weight": "REAL", "name": "TEXT", "model_score": "REAL",
        "factor_coverage": "REAL", "cash_weight": "REAL",
        "constraint_note": "TEXT", "rebalance_action": "TEXT",
    }.items():
        if column not in holding_columns:
            conn.execute(f"ALTER TABLE backtest_holdings ADD COLUMN {column} {definition}")


def _experiment_local_date(value) -> str:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        timestamp = pd.Timestamp.now(tz="Asia/Shanghai")
    elif timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("Asia/Shanghai")
    else:
        timestamp = timestamp.tz_convert("Asia/Shanghai")
    return timestamp.strftime("%Y年%m月%d日")


def _backfill_experiment_versions(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()}
    if not {"version_name", "experiment_note"}.issubset(columns):
        return
    rows = conn.execute(
        "SELECT experiment_id, name, created_at, version_name, experiment_note "
        "FROM experiments ORDER BY created_at, experiment_id"
    ).fetchall()
    sequences: dict[str, int] = {}
    for row in rows:
        version_name = row[3]
        if version_name:
            match = re.match(r"^(\d{4}年\d{2}月\d{2}日)-第(\d+)版$", str(version_name))
            if match:
                sequences[match.group(1)] = max(sequences.get(match.group(1), 0), int(match.group(2)))
    for experiment_id, old_name, created_at, version_name, experiment_note in rows:
        if not version_name:
            date_label = _experiment_local_date(created_at)
            sequences[date_label] = sequences.get(date_label, 0) + 1
            version_name = f"{date_label}-第{sequences[date_label]:03d}版"
        note = experiment_note
        if not note and old_name and str(old_name) != str(version_name):
            note = str(old_name)
        conn.execute(
            "UPDATE experiments SET version_name = ?, experiment_note = ?, name = ? "
            "WHERE experiment_id = ?",
            (version_name, note, version_name, experiment_id),
        )


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
        counts = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names}
        active = conn.execute(
            "SELECT value_json FROM research_settings WHERE setting_key = 'active_universe'"
        ).fetchone()
        if active is not None:
            try:
                active_payload = json.loads(active[0])
                active_symbols = {str(symbol) for symbol in active_payload.get("symbols", []) if symbol}
                if active_symbols:
                    counts["security_master"] = len(active_symbols)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return counts


READABLE_TABLES = {
    "security_master", "daily_prices", "dividends", "corporate_actions",
    "fundamentals", "monthly_universe", "monthly_features",
    "experiment_universe", "forward_returns", "rank_ic_monthly",
    "experiment_factor_ic", "backtest_monthly", "backtest_holdings",
    "experiments", "research_settings", "update_logs",
}


def read_table(
    table: str,
    path: str | Path = DEFAULT_DB_PATH,
    *,
    filters: Mapping[str, object] | None = None,
    columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Read only the requested slice of an application table.

    Filtering in SQLite is important on Streamlit Community Cloud: reading a
    complete history and filtering it afterwards can temporarily hold several
    copies of the same large DataFrame during every widget rerun.
    """
    initialize_database(path)
    if table not in READABLE_TABLES:
        raise ValueError(f"不允许读取表: {table}")
    with connect(path) as conn:
        allowed_columns = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        selected = list(columns) if columns is not None else ["*"]
        invalid = [column for column in selected if column != "*" and column not in allowed_columns]
        if invalid:
            raise ValueError(f"{table} 不存在列: {', '.join(invalid)}")
        clauses: list[str] = []
        params: list[object] = []
        for column, value in (filters or {}).items():
            if column not in allowed_columns:
                raise ValueError(f"{table} 不存在筛选列: {column}")
            if value is None:
                clauses.append(f"{column} IS NULL")
            elif isinstance(value, (list, tuple, set, frozenset)):
                values = list(value)
                if not values:
                    clauses.append("1 = 0")
                else:
                    clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
                    params.extend(values)
            else:
                clauses.append(f"{column} = ?")
                params.append(value)
        sql = f"SELECT {','.join(selected)} FROM {table}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return pd.read_sql_query(sql, conn, params=params)


def latest_feature_summary(path: str | Path = DEFAULT_DB_PATH) -> tuple[str | None, int]:
    initialize_database(path)
    with connect(path) as conn:
        latest = conn.execute("SELECT MAX(month_end) FROM monthly_features").fetchone()[0]
        if latest is None:
            return None, 0
        count = conn.execute(
            "SELECT COUNT(DISTINCT symbol) FROM monthly_features WHERE month_end = ?",
            (latest,),
        ).fetchone()[0]
    return str(latest), int(count or 0)


def minimum_stock_trade_date(path: str | Path = DEFAULT_DB_PATH) -> str | None:
    initialize_database(path)
    with connect(path) as conn:
        value = conn.execute(
            "SELECT MIN(trade_date) FROM daily_prices WHERE symbol NOT LIKE '^%'"
        ).fetchone()[0]
    return str(value) if value is not None else None


def read_recent_stock_prices(
    path: str | Path = DEFAULT_DB_PATH,
    lookback: int = 60,
    *,
    symbols: Iterable[str] | None = None,
    as_of=None,
) -> pd.DataFrame:
    """Return a deterministic recent slice and listing-day count.

    ``as_of`` gives every security the same information cutoff.  ``symbols``
    limits the query to the currently imported universe so stale master rows
    from an older CSV cannot silently re-enter a risk snapshot.
    """
    initialize_database(path)
    requested = sorted({str(symbol) for symbol in (symbols or []) if symbol})
    clauses = ["symbol NOT LIKE '^%'"]
    params: list[object] = []
    if requested:
        clauses.append(f"symbol IN ({','.join('?' for _ in requested)})")
        params.extend(requested)
    if as_of is not None:
        clauses.append("trade_date <= ?")
        params.append(pd.Timestamp(as_of).date().isoformat())
    params.append(int(lookback))
    with connect(path) as conn:
        return pd.read_sql_query(
            f"""
            WITH ranked AS (
              SELECT symbol, trade_date, close, volume,
                     ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS recent_rank,
                     COUNT(*) OVER (PARTITION BY symbol) AS listing_days
              FROM daily_prices
              WHERE {' AND '.join(clauses)}
            )
            SELECT symbol, trade_date, close, volume, listing_days
            FROM ranked
            WHERE recent_rank <= ?
            ORDER BY symbol, trade_date
            """,
            conn,
            params=params,
        )


def resolve_stock_data_cutoff(
    path: str | Path = DEFAULT_DB_PATH,
    symbols: Iterable[str] | None = None,
) -> dict:
    """Return the modal latest trading date for a stock universe.

    Using the newest date held by just one security can expose a partially
    completed Yahoo batch.  The modal per-symbol latest date represents the
    date shared by the largest part of the active universe and is stable for a
    fixed database revision.
    """
    initialize_database(path)
    requested = sorted({str(symbol) for symbol in (symbols or []) if symbol})
    clauses = ["symbol NOT LIKE '^%'"]
    params: list[object] = []
    if requested:
        clauses.append(f"symbol IN ({','.join('?' for _ in requested)})")
        params.extend(requested)
    with connect(path) as conn:
        rows = conn.execute(
            f"""
            SELECT latest_date, COUNT(*) AS symbol_count
            FROM (
              SELECT symbol, MAX(trade_date) AS latest_date
              FROM daily_prices
              WHERE {' AND '.join(clauses)}
              GROUP BY symbol
            )
            WHERE latest_date IS NOT NULL
            GROUP BY latest_date
            ORDER BY symbol_count DESC, latest_date DESC
            """,
            params,
        ).fetchall()
        available = conn.execute(
            f"SELECT COUNT(DISTINCT symbol) FROM daily_prices WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()[0]
    if not rows:
        return {
            "as_of": None,
            "aligned_symbols": 0,
            "available_symbols": int(available or 0),
            "requested_symbols": len(requested),
        }
    return {
        "as_of": str(rows[0][0]),
        "aligned_symbols": int(rows[0][1]),
        "available_symbols": int(available or 0),
        "requested_symbols": len(requested),
    }


def export_table_csv(table: str, path: str | Path = DEFAULT_DB_PATH) -> bytes:
    return read_table(table, path).to_csv(index=False).encode("utf-8-sig")


def save_setting(key: str, value, path: str | Path = DEFAULT_DB_PATH) -> None:
    initialize_database(path)
    with connect(path) as conn:
        upsert_rows(
            conn,
            "research_settings",
            [{
                "setting_key": key,
                "value_json": json.dumps(value, ensure_ascii=False),
                "updated_at": pd.Timestamp.now().isoformat(),
            }],
        )


def load_setting(key: str, default=None, path: str | Path = DEFAULT_DB_PATH):
    initialize_database(path)
    with connect(path) as conn:
        row = conn.execute(
            "SELECT value_json FROM research_settings WHERE setting_key = ?",
            (key,),
        ).fetchone()
    return json.loads(row[0]) if row is not None else default


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
