from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import DEFAULT_DB_PATH
from .database import connect, initialize_database, upsert_rows


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
    }
    with connect(path) as conn:
        upsert_rows(conn, "experiments", [row], preserve_existing_on_null=True)
    return experiment_id


def list_experiments(path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    initialize_database(path)
    with connect(path) as conn:
        frame = pd.read_sql_query("SELECT * FROM experiments ORDER BY score DESC, created_at DESC", conn)
    if not frame.empty:
        metrics = frame["metrics_json"].apply(lambda value: json.loads(value or "{}"))
        for key in sorted({key for item in metrics for key in item}):
            frame[key] = metrics.apply(lambda item: item.get(key))
    return frame


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
    ]
    data = frame.copy()
    for column in allowed:
        if column not in data:
            data[column] = None
    data["is_out_of_sample"] = pd.to_numeric(data["is_out_of_sample"], errors="coerce").fillna(1).astype(int)
    data["survivor_bias"] = pd.to_numeric(data["survivor_bias"], errors="coerce").fillna(0).astype(int)
    data["factor_weights_json"] = data["factor_weights_json"].fillna("{}")
    data["group_weights_json"] = data["group_weights_json"].fillna("{}")
    data["metrics_json"] = data["metrics_json"].fillna("{}")
    with connect(path) as conn:
        return upsert_rows(conn, "experiments", data[allowed].to_dict("records"))
