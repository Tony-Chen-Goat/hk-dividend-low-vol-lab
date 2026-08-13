import pandas as pd

from app.data_quality import database_quality_snapshot
from app.database import (
    connect,
    initialize_database,
    latest_feature_summary,
    read_recent_stock_prices,
    read_table,
    upsert_rows,
)
from app.research_pipeline import load_feature_panel


def test_quality_and_latest_summaries_do_not_materialize_history(tmp_path):
    path = tmp_path / "memory.sqlite3"
    initialize_database(path)
    with connect(path) as conn:
        upsert_rows(conn, "security_master", [{"symbol": "0005.HK", "source": "test"}])
        upsert_rows(conn, "daily_prices", [
            {
                "symbol": "0005.HK", "trade_date": f"2026-01-{day:02d}",
                "close": float(day), "volume": 1000, "source": "test",
            }
            for day in range(1, 21)
        ])
        upsert_rows(conn, "monthly_features", [
            {
                "experiment_id": "exp", "model_name": "yahoo_10",
                "month_end": month, "symbol": "0005.HK", "raw_json": "{}",
            }
            for month in ["2025-12-31", "2026-01-31"]
        ])

    snapshot = database_quality_snapshot(path)
    latest, count = latest_feature_summary(path)
    recent = read_recent_stock_prices(path, 5)
    panel = load_feature_panel(path, "yahoo_10", "exp", latest_only=True)

    assert snapshot["price_coverage"] == 1.0
    assert (latest, count) == ("2026-01-31", 1)
    assert len(recent) == 5
    assert recent["listing_days"].iloc[0] == 20
    assert panel["month_end"].tolist() == [pd.Timestamp("2026-01-31")]


def test_read_table_filters_rows_in_sqlite(tmp_path):
    path = tmp_path / "filter.sqlite3"
    initialize_database(path)
    with connect(path) as conn:
        upsert_rows(conn, "backtest_monthly", [
            {"experiment_id": experiment, "month_end": "2026-01-31", "net_value": 1.0}
            for experiment in ["a", "b", "c"]
        ])
    frame = read_table(
        "backtest_monthly", path,
        filters={"experiment_id": ["a", "c"]},
        columns=["experiment_id", "net_value"],
    )
    assert set(frame["experiment_id"]) == {"a", "c"}
    assert list(frame.columns) == ["experiment_id", "net_value"]
