from __future__ import annotations

import json
import io
import uuid
import zipfile
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import DEFAULT_DB_PATH
from .database import connect, initialize_database, read_table, upsert_rows


_EXPERIMENT_FRAME_DEFAULTS = {
    "model_name": None,
    "universe_name": None,
    "data_start": None,
    "data_end": None,
    "train_window": None,
    "validation_window": None,
    "portfolio_method": None,
    "selected_count": None,
    "max_stock_weight": None,
    "max_sector_weight": None,
    "transaction_cost": None,
    "score": None,
    "coverage": None,
    "status": "features_ready",
    "risk_settings_json": "{}",
    "backtest_settings_json": "{}",
    "approved": 0,
}


def _normalize_experiment_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep pages usable while a legacy Cloud SQLite schema is being migrated."""
    result = frame.copy()
    for column, default in _EXPERIMENT_FRAME_DEFAULTS.items():
        if column not in result.columns:
            result[column] = default
        elif default is not None:
            result[column] = result[column].fillna(default)
    return result


def experiment_score(
    rank_icir: float,
    information_ratio: float,
    max_drawdown: float,
    average_turnover: float,
) -> float:
    values = [rank_icir, information_ratio, max_drawdown, average_turnover]
    clean = [0.0 if value is None or not math.isfinite(float(value)) else float(value) for value in values]
    icir, information, drawdown, turnover = clean
    return icir + 0.5 * information - 0.5 * drawdown - 0.2 * turnover


def save_experiment(payload: dict, path: str | Path = DEFAULT_DB_PATH) -> str:
    initialize_database(path)
    experiment_id = payload.get("experiment_id") or uuid.uuid4().hex[:12]
    metrics = payload.get("metrics", {})
    row = {
        "experiment_id": experiment_id,
        "name": payload.get("name", experiment_id),
        "created_at": payload.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "model_name": payload.get("model_name"),
        "universe_name": payload.get("universe_name"), "data_start": payload.get("data_start"),
        "data_end": payload.get("data_end"), "train_window": payload.get("train_window"),
        "validation_window": payload.get("validation_window"),
        "factor_weights_json": json.dumps(payload.get("factor_weights", {}), ensure_ascii=False),
        "group_weights_json": json.dumps(payload.get("group_weights", {}), ensure_ascii=False),
        "portfolio_method": payload.get("portfolio_method", "blend"),
        "selected_count": payload.get("selected_count", 30), "max_stock_weight": payload.get("max_stock_weight", 0.05),
        "max_sector_weight": payload.get("max_sector_weight", 0.25), "transaction_cost": payload.get("transaction_cost", 0.001),
        "metrics_json": json.dumps(metrics, ensure_ascii=False), "score": payload.get("score"),
        "coverage": payload.get("coverage"), "survivor_bias": int(bool(payload.get("survivor_bias", False))),
        "quality_note": payload.get("quality_note"), "is_out_of_sample": int(bool(payload.get("is_out_of_sample", True))),
        "status": payload.get("status", "features_ready"),
        "risk_settings_json": json.dumps(payload.get("risk_settings", {}), ensure_ascii=False),
        "backtest_settings_json": json.dumps(payload.get("backtest_settings", {}), ensure_ascii=False),
        "approved": int(bool(payload.get("approved", False))),
    }
    with connect(path) as conn:
        upsert_rows(conn, "experiments", [row], preserve_existing_on_null=True)
    return experiment_id


def list_experiments(path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    initialize_database(path)
    with connect(path) as conn:
        frame = pd.read_sql_query("SELECT * FROM experiments ORDER BY score DESC, created_at DESC", conn)
    frame = _normalize_experiment_frame(frame)
    if not frame.empty:
        metrics = frame["metrics_json"].apply(lambda value: json.loads(value or "{}"))
        for key in sorted({key for item in metrics for key in item}):
            frame[key] = metrics.apply(lambda item: item.get(key))
    return frame


def get_experiment(experiment_id: str, path: str | Path = DEFAULT_DB_PATH) -> dict:
    initialize_database(path)
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"实验不存在: {experiment_id}")
    result = dict(row)
    for column in ["factor_weights_json", "group_weights_json", "metrics_json", "risk_settings_json", "backtest_settings_json"]:
        result[column.removesuffix("_json")] = json.loads(result.get(column) or "{}")
    return result


def update_experiment(
    experiment_id: str,
    *,
    metrics: dict | None = None,
    path: str | Path = DEFAULT_DB_PATH,
    **fields,
) -> None:
    allowed = {
        "name", "status", "portfolio_method", "selected_count",
        "max_stock_weight", "max_sector_weight", "transaction_cost", "score",
        "coverage", "quality_note", "is_out_of_sample", "approved",
        "backtest_settings_json", "risk_settings_json",
    }
    invalid = set(fields) - allowed
    if invalid:
        raise ValueError(f"不允许更新实验字段: {', '.join(sorted(invalid))}")
    initialize_database(path)
    if metrics is not None:
        current = get_experiment(experiment_id, path).get("metrics", {})
        current.update(metrics)
        fields["metrics_json"] = json.dumps(current, ensure_ascii=False)
        allowed.add("metrics_json")
    if not fields:
        return
    assignments = ", ".join(f"{column} = ?" for column in fields)
    values = []
    for column, value in fields.items():
        if column in {"approved", "is_out_of_sample"}:
            value = int(bool(value))
        elif column.endswith("_json") and isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        values.append(value)
    with connect(path) as conn:
        conn.execute(
            f"UPDATE experiments SET {assignments} WHERE experiment_id = ?",
            [*values, experiment_id],
        )


def approve_experiment(experiment_id: str, path: str | Path = DEFAULT_DB_PATH) -> None:
    initialize_database(path)
    with connect(path) as conn:
        conn.execute("UPDATE experiments SET approved = 0")
        conn.execute(
            "UPDATE experiments SET approved = 1 WHERE experiment_id = ?",
            (experiment_id,),
        )


def store_rank_ic_results(
    experiment_id: str,
    monthly: pd.DataFrame,
    summary: dict,
    factor_comparison: pd.DataFrame | None = None,
    path: str | Path = DEFAULT_DB_PATH,
) -> None:
    rows = []
    for row in monthly.to_dict("records"):
        rows.append({
            "experiment_id": experiment_id,
            "month_end": pd.Timestamp(row["month_end"]).date().isoformat(),
            "rank_ic": row.get("rank_ic"), "valid_count": row.get("valid_count"),
            "skip_reason": row.get("skip_reason"),
            "cumulative_rank_ic": row.get("cumulative_rank_ic"),
            "rolling_12m_ic": row.get("rolling_12m_ic"),
        })
    initialize_database(path)
    with connect(path) as conn:
        conn.execute("DELETE FROM rank_ic_monthly WHERE experiment_id = ?", (experiment_id,))
        upsert_rows(conn, "rank_ic_monthly", rows)
        if factor_comparison is not None:
            conn.execute("DELETE FROM experiment_factor_ic WHERE experiment_id = ?", (experiment_id,))
            factor_rows = []
            for row in factor_comparison.to_dict("records"):
                factor_rows.append({"experiment_id": experiment_id, **row})
            upsert_rows(conn, "experiment_factor_ic", factor_rows)
    current_status = get_experiment(experiment_id, path).get("status")
    update_experiment(
        experiment_id,
        metrics=summary,
        status="completed" if current_status == "completed" else "rank_ic_ready",
        path=path,
    )


def store_backtest_results(
    experiment_id: str,
    monthly: pd.DataFrame,
    holdings: pd.DataFrame,
    metrics: dict,
    settings: dict,
    score: float,
    path: str | Path = DEFAULT_DB_PATH,
) -> None:
    monthly_columns = [
        "month_end", "gross_return", "transaction_cost", "net_return", "turnover",
        "cash_weight", "selected_count", "entered_count", "exited_count",
        "entered_symbols", "exited_symbols", "retained_symbols", "net_value",
        "gross_value", "drawdown",
    ]
    holding_columns = [
        "month_end", "symbol", "target_weight", "raw_weight", "forward_return",
        "contribution", "sector", "name", "model_score", "factor_coverage",
        "cash_weight", "constraint_note", "rebalance_action",
    ]
    monthly_rows = []
    for row in monthly[[column for column in monthly_columns if column in monthly]].to_dict("records"):
        row["experiment_id"] = experiment_id
        row["month_end"] = pd.Timestamp(row["month_end"]).date().isoformat()
        monthly_rows.append(row)
    holding_rows = []
    for row in holdings[[column for column in holding_columns if column in holdings]].to_dict("records"):
        row["experiment_id"] = experiment_id
        row["month_end"] = pd.Timestamp(row["month_end"]).date().isoformat()
        row["actual_return"] = row.pop("forward_return", None)
        holding_rows.append(row)
    initialize_database(path)
    with connect(path) as conn:
        conn.execute("DELETE FROM backtest_monthly WHERE experiment_id = ?", (experiment_id,))
        conn.execute("DELETE FROM backtest_holdings WHERE experiment_id = ?", (experiment_id,))
        upsert_rows(conn, "backtest_monthly", monthly_rows)
        upsert_rows(conn, "backtest_holdings", holding_rows)
    update_experiment(
        experiment_id,
        metrics=metrics,
        status="completed",
        score=score,
        portfolio_method=settings.get("portfolio_method", "blend"),
        selected_count=settings.get("selected_count"),
        max_stock_weight=settings.get("max_stock_weight"),
        max_sector_weight=settings.get("max_sector_weight"),
        transaction_cost=settings.get("transaction_cost"),
        backtest_settings_json=settings,
        path=path,
    )


def export_experiment_bundle(experiment_id: str, path: str | Path = DEFAULT_DB_PATH) -> bytes:
    experiment = get_experiment(experiment_id, path)
    tables = {
        "rank_ic_monthly.csv": read_table("rank_ic_monthly", path),
        "factor_ic_comparison.csv": read_table("experiment_factor_ic", path),
        "backtest_monthly.csv": read_table("backtest_monthly", path),
        "backtest_holdings.csv": read_table("backtest_holdings", path),
        "experiment_universe.csv": read_table("experiment_universe", path),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "experiment.json",
            json.dumps(experiment, ensure_ascii=False, indent=2, default=str),
        )
        for filename, frame in tables.items():
            subset = frame[frame["experiment_id"] == experiment_id] if "experiment_id" in frame else frame
            archive.writestr(filename, subset.to_csv(index=False).encode("utf-8-sig"))
        features = read_table("monthly_features", path)
        features = features[features["experiment_id"] == experiment_id].copy()
        summary_rows = []
        for row in features.to_dict("records"):
            payload = {
                "experiment_id": row["experiment_id"], "model_name": row["model_name"],
                "month_end": row["month_end"], "symbol": row["symbol"],
                "model_score": row.get("model_score"), "coverage": row.get("coverage"),
                "quality_flag": row.get("quality_flag"), "next_month_end": row.get("next_month_end"),
                "forward_return": row.get("forward_return"),
            }
            payload.update(json.loads(row.get("raw_json") or "{}"))
            payload.update({
                f"{key}__winsorized": value
                for key, value in json.loads(row.get("winsorized_json") or "{}").items()
            })
            payload.update({
                f"{key}__score": value
                for key, value in json.loads(row.get("score_json") or "{}").items()
            })
            payload.update({
                f"{key}__contribution": value
                for key, value in json.loads(row.get("contribution_json") or "{}").items()
            })
            summary_rows.append(payload)
        archive.writestr(
            "monthly_features.csv",
            pd.DataFrame(summary_rows).to_csv(index=False).encode("utf-8-sig"),
        )
    return output.getvalue()


def import_experiments_csv(frame: pd.DataFrame, path: str | Path = DEFAULT_DB_PATH) -> int:
    required = {"experiment_id", "name", "created_at"}
    if missing := required - set(frame.columns):
        raise ValueError(f"实验 CSV 缺少列: {', '.join(sorted(missing))}")
    initialize_database(path)
    allowed = [
        "experiment_id", "name", "created_at", "model_name", "universe_name", "data_start", "data_end", "train_window",
        "validation_window", "factor_weights_json", "group_weights_json", "portfolio_method", "selected_count",
        "max_stock_weight", "max_sector_weight", "transaction_cost", "metrics_json", "score", "coverage",
        "survivor_bias", "quality_note", "is_out_of_sample",
        "status", "risk_settings_json", "backtest_settings_json", "approved",
    ]
    data = frame.copy()
    for column in allowed:
        if column not in data:
            data[column] = None
    data["is_out_of_sample"] = pd.to_numeric(data["is_out_of_sample"], errors="coerce").fillna(1).astype(int)
    data["survivor_bias"] = pd.to_numeric(data["survivor_bias"], errors="coerce").fillna(0).astype(int)
    data["approved"] = pd.to_numeric(data["approved"], errors="coerce").fillna(0).astype(int)
    data["status"] = data["status"].fillna("imported")
    data["factor_weights_json"] = data["factor_weights_json"].fillna("{}")
    data["group_weights_json"] = data["group_weights_json"].fillna("{}")
    data["metrics_json"] = data["metrics_json"].fillna("{}")
    with connect(path) as conn:
        return upsert_rows(conn, "experiments", data[allowed].to_dict("records"))
