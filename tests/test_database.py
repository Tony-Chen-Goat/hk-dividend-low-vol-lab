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


def test_sqlite_upsert_can_preserve_existing_values_on_null(tmp_path):
    path = tmp_path / "test.sqlite3"
    initialize_database(path)
    original = {
        "symbol": "0700.HK",
        "name": "Tencent Holdings",
        "sector": "Information Technology",
        "index_membership": "HSI|HSCEI",
    }
    with connect(path) as conn:
        upsert_rows(conn, "security_master", [original])
        upsert_rows(
            conn,
            "security_master",
            [{"symbol": "0700.HK", "name": None, "sector": None}],
            preserve_existing_on_null=True,
        )

    frame = read_table("security_master", path)
    assert frame.iloc[0]["name"] == "Tencent Holdings"
    assert frame.iloc[0]["sector"] == "Information Technology"
    assert frame.iloc[0]["index_membership"] == "HSI|HSCEI"


def test_experiment_versions_can_coexist_for_same_symbol_and_month(tmp_path):
    path = tmp_path / "test.sqlite3"
    initialize_database(path)
    rows = [
        {
            "experiment_id": "E-Y10",
            "model_name": "yahoo_10",
            "month_end": "2026-07-31",
            "symbol": "0700.HK",
            "model_score": 70.0,
        },
        {
            "experiment_id": "E-F13",
            "model_name": "full_13",
            "month_end": "2026-07-31",
            "symbol": "0700.HK",
            "model_score": 80.0,
        },
    ]
    with connect(path) as conn:
        upsert_rows(conn, "monthly_features", rows)

    frame = read_table("monthly_features", path)
    assert len(frame) == 2
    assert set(frame["model_name"]) == {"yahoo_10", "full_13"}
    assert set(frame["experiment_id"]) == {"E-Y10", "E-F13"}


def test_legacy_monthly_features_are_migrated_to_full_13(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE monthly_features (
              month_end TEXT NOT NULL, symbol TEXT NOT NULL,
              raw_json TEXT, winsorized_json TEXT, score_json TEXT,
              contribution_json TEXT, model_score REAL, coverage REAL,
              quality_flag TEXT, PRIMARY KEY (month_end, symbol)
            )
            """
        )
        conn.execute(
            "INSERT INTO monthly_features (month_end, symbol, model_score) VALUES (?, ?, ?)",
            ("2026-07-31", "0700.HK", 75.0),
        )

    initialize_database(path)
    frame = read_table("monthly_features", path)
    assert len(frame) == 1
    assert frame.iloc[0]["model_name"] == "full_13"
    assert frame.iloc[0]["experiment_id"] == "legacy-full_13"


def test_experiment_save_and_update(tmp_path):
    path = tmp_path / "test.sqlite3"
    experiment_id = save_experiment({"experiment_id": "BASE", "name": "BASELINE", "model_name": "yahoo_10", "metrics": {"rank_icir": 0.5}, "score": 0.4}, path)
    save_experiment({"experiment_id": experiment_id, "name": "BASELINE", "metrics": {"rank_icir": 0.6}, "score": 0.5}, path)
    frame = list_experiments(path)
    assert len(frame) == 1
    assert frame.iloc[0]["rank_icir"] == 0.6
    assert frame.iloc[0]["model_name"] == "yahoo_10"


def test_csv_export_and_experiment_import(tmp_path):
    path = tmp_path / "test.sqlite3"
    initialize_database(path)
    frame = pd.DataFrame({"experiment_id": ["E1"], "name": ["Experiment"], "created_at": ["2024-01-01T00:00:00Z"]})
    assert import_experiments_csv(frame, path) == 1
    assert b"experiment_id" in export_table_csv("experiments", path)
