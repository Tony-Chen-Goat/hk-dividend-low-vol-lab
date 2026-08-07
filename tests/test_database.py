import json

import pandas as pd

from app.database import connect, export_table_csv, initialize_database, read_table, upsert_rows
from app.experiment_store import import_experiments_csv, list_experiments, save_experiment


def test_sqlite_upsert_deduplicates(tmp_path):
    path = tmp_path / "test.sqlite3"
    initialize_database(path)
    row = {"symbol": "0700.HK", "trade_date": "2024-01-02", "close": 300.0, "source": "test"}
    with connect(path) as conn:
        upsert_rows(conn, "daily_prices", [row])
        upsert_rows(conn, "daily_prices", [{**row, "close": 301.0}])
    frame = read_table("daily_prices", path)
    assert len(frame) == 1
    assert frame.iloc[0]["close"] == 301


def test_sqlite_upsert_converts_pandas_nat_to_null(tmp_path):
    path = tmp_path / "test.sqlite3"
    initialize_database(path)
    row = {
        "symbol": "0700.HK",
        "effective_date": pd.Timestamp("2026-06-08"),
        "end_date": pd.NaT,
        "source": "test",
    }
    with connect(path) as conn:
        upsert_rows(conn, "security_master", [row])

    frame = read_table("security_master", path)
    assert frame.iloc[0]["effective_date"].startswith("2026-06-08")
    assert pd.isna(frame.iloc[0]["end_date"])


def test_experiment_save_and_update(tmp_path):
    path = tmp_path / "test.sqlite3"
    experiment_id = save_experiment({"experiment_id": "BASE", "name": "BASELINE", "metrics": {"rank_icir": 0.5}, "score": 0.4}, path)
    save_experiment({"experiment_id": experiment_id, "name": "BASELINE", "metrics": {"rank_icir": 0.6}, "score": 0.5}, path)
    frame = list_experiments(path)
    assert len(frame) == 1
    assert frame.iloc[0]["rank_icir"] == 0.6


def test_csv_export_and_experiment_import(tmp_path):
    path = tmp_path / "test.sqlite3"
    initialize_database(path)
    frame = pd.DataFrame({"experiment_id": ["E1"], "name": ["Experiment"], "created_at": ["2024-01-01T00:00:00Z"]})
    assert import_experiments_csv(frame, path) == 1
    assert b"experiment_id" in export_table_csv("experiments", path)
