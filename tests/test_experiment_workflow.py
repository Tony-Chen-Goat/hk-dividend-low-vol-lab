import json
import zipfile
from io import BytesIO

import pandas as pd

from app.database import connect, initialize_database, read_table, upsert_rows
from app.experiment_store import (
    approve_experiment,
    experiment_score,
    export_experiment_bundle,
    get_experiment,
    list_experiments,
    next_experiment_version_name,
    save_experiment,
    store_backtest_results,
    store_rank_ic_results,
)


def test_experiment_score_formula():
    assert abs(experiment_score(1.0, 0.5, 0.2, 0.3) - 1.09) < 1e-12


def test_experiment_versions_use_local_date_sequence_and_keep_notes(tmp_path):
    path = tmp_path / "versions.sqlite3"
    first = save_experiment({
        "experiment_id": "E1",
        "name": "默认权重",
        "created_at": "2026-08-13T01:00:00+00:00",
        "model_name": "yahoo_10",
    }, path)
    second = save_experiment({
        "experiment_id": "E2",
        "name": "低波加强",
        "created_at": "2026-08-13T02:00:00+00:00",
        "model_name": "yahoo_10",
    }, path)

    first_record = get_experiment(first, path)
    second_record = get_experiment(second, path)

    assert first_record["version_name"] == "2026年08月13日-第001版"
    assert second_record["version_name"] == "2026年08月13日-第002版"
    assert first_record["experiment_note"] == "默认权重"
    assert second_record["display_name"] == "2026年08月13日-第002版｜低波加强"
    assert next_experiment_version_name(path, "2026-08-13T03:00:00+00:00") == "2026年08月13日-第003版"


def test_manual_experiment_workflow_can_be_archived_and_approved(tmp_path):
    path = tmp_path / "workflow.sqlite3"
    experiment_id = save_experiment(
        {
            "experiment_id": "EXP-1",
            "name": "手动实验一",
            "model_name": "yahoo_10",
            "factor_weights": {"dividend_yield_ttm": 1.0},
            "risk_settings": {"allow_reit": True},
            "status": "features_ready",
        },
        path,
    )
    with connect(path) as conn:
        upsert_rows(conn, "monthly_features", [{
            "experiment_id": experiment_id,
            "model_name": "yahoo_10",
            "month_end": "2024-01-31",
            "symbol": "0005.HK",
            "model_score": 80.0,
            "coverage": 1.0,
            "forward_return": 0.02,
        }])
        upsert_rows(conn, "experiment_universe", [{
            "experiment_id": experiment_id,
            "month_end": "2024-01-31",
            "symbol": "0005.HK",
            "included": 1,
            "source": "test",
        }])

    rank_monthly = pd.DataFrame({
        "month_end": pd.to_datetime(["2024-01-31"]),
        "rank_ic": [0.1],
        "valid_count": [10],
        "skip_reason": [None],
        "cumulative_rank_ic": [0.1],
        "rolling_12m_ic": [0.1],
    })
    store_rank_ic_results(
        experiment_id,
        rank_monthly,
        {"mean_rank_ic": 0.1, "rank_icir": 0.5},
        pd.DataFrame([{"factor": "dividend_yield_ttm__score", "mean_rank_ic": 0.1}]),
        path,
    )
    backtest_monthly = pd.DataFrame({
        "month_end": pd.to_datetime(["2024-01-31"]),
        "gross_return": [0.02], "transaction_cost": [0.001],
        "net_return": [0.019], "turnover": [0.5], "cash_weight": [0.0],
        "selected_count": [1], "entered_count": [1], "exited_count": [0],
        "entered_symbols": ["0005.HK"], "exited_symbols": [""],
        "retained_symbols": [""], "net_value": [1.019],
        "gross_value": [1.02], "drawdown": [0.0],
    })
    holdings = pd.DataFrame({
        "month_end": pd.to_datetime(["2024-01-31"]),
        "symbol": ["0005.HK"], "target_weight": [1.0], "raw_weight": [1.0],
        "forward_return": [0.02], "contribution": [0.02], "sector": ["金融"],
        "name": ["汇丰控股"], "model_score": [80.0], "factor_coverage": [1.0],
        "cash_weight": [0.0], "constraint_note": ["满足约束"],
        "rebalance_action": ["新进入"],
    })
    store_backtest_results(
        experiment_id,
        backtest_monthly,
        holdings,
        {"annualized_return": 0.2, "rank_icir": 0.5},
        {
            "portfolio_method": "blend", "selected_count": 3,
            "max_stock_weight": 0.5, "max_sector_weight": 1.0,
            "transaction_cost": 0.001,
        },
        0.3,
        path,
    )
    approve_experiment(experiment_id, path)

    experiment = get_experiment(experiment_id, path)
    assert experiment["status"] == "completed"
    assert experiment["approved"] == 1
    assert experiment["metrics"]["mean_rank_ic"] == 0.1
    assert experiment["metrics"]["annualized_return"] == 0.2
    assert len(read_table("rank_ic_monthly", path)) == 1
    assert len(read_table("backtest_monthly", path)) == 1
    assert len(read_table("backtest_holdings", path)) == 1

    bundle = export_experiment_bundle(experiment_id, path)
    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        assert "experiment.json" in archive.namelist()
        assert "monthly_features.csv" in archive.namelist()
        payload = json.loads(archive.read("experiment.json"))
        assert payload["experiment_id"] == experiment_id

    store_rank_ic_results(
        experiment_id,
        rank_monthly,
        {"mean_rank_ic": 0.11, "rank_icir": 0.55},
        path=path,
    )
    assert get_experiment(experiment_id, path)["status"] == "completed"


def test_previous_schema_migrates_without_new_experiment_columns(tmp_path):
    path = tmp_path / "previous.sqlite3"
    with connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE forward_returns (
              month_end TEXT NOT NULL, symbol TEXT NOT NULL,
              next_month_end TEXT, forward_return REAL,
              PRIMARY KEY (month_end, symbol)
            );
            CREATE TABLE experiments (
              experiment_id TEXT PRIMARY KEY, name TEXT NOT NULL,
              created_at TEXT NOT NULL, model_name TEXT,
              factor_weights_json TEXT, group_weights_json TEXT,
              metrics_json TEXT, survivor_bias INTEGER,
              quality_note TEXT, is_out_of_sample INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE monthly_features (
              model_name TEXT NOT NULL DEFAULT 'full_13',
              month_end TEXT NOT NULL, symbol TEXT NOT NULL,
              raw_json TEXT, winsorized_json TEXT, score_json TEXT,
              contribution_json TEXT, model_score REAL, coverage REAL,
              quality_flag TEXT, PRIMARY KEY (model_name, month_end, symbol)
            );
            INSERT INTO monthly_features (
              model_name, month_end, symbol, model_score
            ) VALUES ('yahoo_10', '2024-01-31', '0005.HK', 80);
            INSERT INTO forward_returns (
              month_end, symbol, next_month_end, forward_return
            ) VALUES ('2024-01-31', '0005.HK', '2024-02-29', 0.02);
            """
        )
    initialize_database(path)
    feature = read_table("monthly_features", path).iloc[0]
    experiment = get_experiment("legacy-yahoo_10", path)
    assert feature["experiment_id"] == "legacy-yahoo_10"
    assert feature["forward_return"] == 0.02
    assert experiment["status"] == "features_ready"


def test_experiment_list_tolerates_legacy_cloud_schema_before_migration(tmp_path, monkeypatch):
    path = tmp_path / "legacy-cloud.sqlite3"
    with connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE experiments (
              experiment_id TEXT PRIMARY KEY, name TEXT NOT NULL,
              created_at TEXT NOT NULL, model_name TEXT,
              factor_weights_json TEXT, group_weights_json TEXT,
              metrics_json TEXT, score REAL
            );
            INSERT INTO experiments (
              experiment_id, name, created_at, model_name,
              factor_weights_json, group_weights_json, metrics_json, score
            ) VALUES (
              'legacy-1', 'Legacy experiment', '2026-08-01', 'yahoo_10',
              '{}', '{}', '{}', 0.1
            );
            """
        )
    monkeypatch.setattr("app.experiment_store.initialize_database", lambda _: None)

    experiments = list_experiments(path)

    assert experiments.loc[0, "status"] == "features_ready"
    assert experiments.loc[0, "approved"] == 0
    assert experiments.loc[0, "risk_settings_json"] == "{}"
