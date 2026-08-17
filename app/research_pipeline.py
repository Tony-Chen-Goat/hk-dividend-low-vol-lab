from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import calculate_forward_returns, run_monthly_backtest
from .config import DEFAULT_DB_PATH, FACTOR_WEIGHTS, MODEL_FACTOR_GROUPS, MODEL_FACTOR_WEIGHTS, MODEL_FULL_13
from .database import connect, initialize_database, load_setting, read_table, resolve_stock_data_cutoff, upsert_rows
from .experiment_store import save_experiment
from .factors import calculate_monthly_features
from .portfolio import build_article_baseline, build_enhanced_portfolio
from .scoring import score_cross_section
from .universe import apply_hk_risk_filters, build_risk_snapshot_at_date, default_filter_settings


def available_month_ends(prices: pd.DataFrame, minimum_history_days: int = 252) -> list[pd.Timestamp]:
    data = prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    unique = sorted(data["trade_date"].dropna().unique())
    if len(unique) < minimum_history_days:
        return []
    dates = pd.DatetimeIndex(unique[minimum_history_days - 1 :])
    return list(pd.Series(dates).groupby(dates.to_period("M")).max())


def compute_and_store_features(
    path: str | Path = DEFAULT_DB_PATH,
    weights: dict[str, float] | None = None,
    progress=None,
    model_name: str = MODEL_FULL_13,
    experiment_id: str | None = None,
    experiment_name: str | None = None,
    risk_settings: dict | None = None,
) -> pd.DataFrame:
    initialize_database(path)
    update_state = load_setting("market_data_update_state", {}, path) or {}
    if update_state.get("status") == "running":
        started = pd.to_datetime(update_state.get("started_at"), errors="coerce", utc=True)
        age_hours = (pd.Timestamp.now(tz="UTC") - started).total_seconds() / 3600 if pd.notna(started) else 0
        if age_hours < 6:
            raise RuntimeError("Yahoo数据仍在更新，不能用半完成数据创建实验。请等待数据中心更新完成。")

    active_universe = load_setting("active_universe", {}, path) or {}
    active_symbols = sorted({str(symbol) for symbol in active_universe.get("symbols", []) if symbol})
    active_filter = {"symbol": active_symbols} if active_symbols else None
    prices = read_table(
        "daily_prices", path,
        filters=active_filter,
        columns=["symbol", "trade_date", "close", "adjusted_close", "volume"],
    )
    dividends = read_table(
        "dividends", path,
        filters=active_filter,
        columns=["symbol", "ex_date", "dividend_per_share"],
    )
    fundamentals = read_table(
        "fundamentals", path,
        filters=active_filter,
        columns=[
            "symbol", "report_period", "published_date", "net_income",
            "operating_cash_flow", "cash_dividends_paid", "free_float_shares",
            "payout_ratio",
        ],
    )
    securities = read_table(
        "security_master", path,
        filters=active_filter,
        columns=[
            "symbol", "name", "sector", "listing_date", "security_type",
            "board", "index_membership", "effective_date", "end_date",
        ],
    )
    if prices.empty:
        return pd.DataFrame()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"], errors="coerce")
    cutoff_meta = resolve_stock_data_cutoff(path, active_symbols)
    data_cutoff = pd.to_datetime(cutoff_meta.get("as_of"), errors="coerce")
    if pd.notna(data_cutoff):
        prices = prices[prices["trade_date"] <= data_cutoff].copy()
    if not dividends.empty:
        dividends["ex_date"] = pd.to_datetime(dividends["ex_date"], errors="coerce")
    if not fundamentals.empty:
        fundamentals["published_date"] = pd.to_datetime(
            fundamentals["published_date"], errors="coerce"
        )
    if not securities.empty:
        stock_symbols = set(securities["symbol"].dropna().astype(str))
        prices = prices[prices["symbol"].isin(stock_symbols)].copy()
        dividends = dividends[dividends["symbol"].isin(stock_symbols)].copy()
        fundamentals = fundamentals[fundamentals["symbol"].isin(stock_symbols)].copy()
    if prices.empty:
        return pd.DataFrame()
    active_weights = weights or dict(MODEL_FACTOR_WEIGHTS[model_name])
    active_risk_settings = {**default_filter_settings(model_name), **(risk_settings or {})}
    active_risk_settings.update({
        "_universe_version": active_universe.get("version") or "legacy-all",
        "_data_revision": int(update_state.get("revision", 0) or 0),
        "_data_cutoff": str(data_cutoff.date()) if pd.notna(data_cutoff) else None,
    })
    experiment_id = save_experiment(
        {
            "experiment_id": experiment_id,
            "name": experiment_name or "手动因子实验",
            "model_name": model_name,
            "universe_name": f"风险过滤后的导入证券池（{active_universe.get('version') or 'legacy-all'}）",
            "data_start": str(pd.to_datetime(prices["trade_date"]).min().date()),
            "data_end": str(pd.to_datetime(prices["trade_date"]).max().date()),
            "factor_weights": active_weights,
            "group_weights": {
                group: sum(active_weights[factor] for factor in factors)
                for group, factors in MODEL_FACTOR_GROUPS[model_name].items()
            },
            "risk_settings": active_risk_settings,
            "coverage": None,
            "survivor_bias": True,
            "quality_note": "证券池、规则、数据修订版和统一截止日已绑定到本实验；使用当前导入证券池回溯历史，仍可能存在幸存者偏差；每月风险过滤仅使用当时及以前的数据。",
            "is_out_of_sample": False,
            "status": "calculating",
        },
        path,
    )
    rows: list[pd.DataFrame] = []
    coverage_values: list[float] = []
    months = available_month_ends(prices)
    forward = calculate_forward_returns(prices)
    forward_lookup = {
        (str(row.symbol), pd.Timestamp(row.month_end)): row
        for row in forward.itertuples()
    }
    forward_rows = [
        {"month_end": pd.Timestamp(row.month_end).date().isoformat(), "symbol": row.symbol,
         "next_month_end": pd.Timestamp(row.next_month_end).date().isoformat() if pd.notna(row.next_month_end) else None,
         "forward_return": _json_value(row.forward_return)}
        for row in forward.itertuples()
    ]
    with connect(path) as conn:
        conn.execute("DELETE FROM monthly_features WHERE experiment_id = ?", (experiment_id,))
        conn.execute("DELETE FROM experiment_universe WHERE experiment_id = ?", (experiment_id,))
        upsert_rows(conn, "forward_returns", forward_rows)

    price_dates = prices["trade_date"]
    date_arrays = {
        str(symbol): np.sort(group["trade_date"].dropna().to_numpy())
        for symbol, group in prices.groupby("symbol", sort=False)
    }
    for index, month in enumerate(months, start=1):
        month = pd.Timestamp(month)
        history_start = pd.Timestamp(year=month.year - 5, month=1, day=1)
        month_prices = prices[(price_dates >= history_start) & (price_dates <= month)].copy()
        month_prices["listing_days"] = month_prices["symbol"].astype(str).map({
            symbol: int(np.searchsorted(values, month.to_datetime64(), side="right"))
            for symbol, values in date_arrays.items()
        })
        month_dividends = dividends
        if not dividends.empty:
            month_dividends = dividends[
                (dividends["ex_date"] >= history_start) & (dividends["ex_date"] <= month)
            ].copy()
        risk_snapshot = build_risk_snapshot_at_date(
            month_prices,
            securities,
            month,
            fundamentals,
        )
        filtered = apply_hk_risk_filters(risk_snapshot, active_risk_settings)
        universe_rows = []
        for row in pd.concat([filtered.included, filtered.excluded], ignore_index=True).to_dict("records"):
            universe_rows.append({
                "experiment_id": experiment_id,
                "month_end": pd.Timestamp(month).date().isoformat(),
                "symbol": row["symbol"],
                "included": int(bool(row.get("included"))),
                "exclusion_reasons": row.get("exclusion_reasons"),
                "source": "point_in_time_risk_filter",
            })
        with connect(path) as conn:
            upsert_rows(conn, "experiment_universe", universe_rows)
        allowed_symbols = set(filtered.included["symbol"].astype(str)) if not filtered.included.empty else set()
        if not allowed_symbols:
            if progress:
                progress(index, len(months), month)
            continue
        raw = calculate_monthly_features(
            month_prices[month_prices["symbol"].isin(allowed_symbols)],
            month_dividends[month_dividends["symbol"].isin(allowed_symbols)] if not month_dividends.empty else month_dividends,
            fundamentals[fundamentals["symbol"].isin(allowed_symbols)] if not fundamentals.empty else fundamentals,
            month,
        )
        if raw.empty:
            continue
        if not securities.empty:
            raw = raw.merge(securities[["symbol", "sector"]], on="symbol", how="left")
        scored = score_cross_section(raw, active_weights)
        scored["model_name"] = model_name
        rows.append(scored[["month_end", "symbol"]].copy())
        stored = []
        for _, row in scored.iterrows():
            forward_row = forward_lookup.get((str(row["symbol"]), pd.Timestamp(month)))
            raw_values = {factor: _json_value(row.get(factor)) for factor in FACTOR_WEIGHTS}
            wins = {factor: _json_value(row.get(f"{factor}__winsorized")) for factor in FACTOR_WEIGHTS}
            scores = {factor: _json_value(row.get(f"{factor}__score")) for factor in FACTOR_WEIGHTS}
            contributions = {factor: _json_value(row.get(f"{factor}__contribution")) for factor in FACTOR_WEIGHTS}
            stored.append({
                "experiment_id": experiment_id, "model_name": model_name,
                "month_end": pd.Timestamp(month).date().isoformat(), "symbol": row["symbol"],
                "raw_json": json.dumps(raw_values, ensure_ascii=False), "winsorized_json": json.dumps(wins, ensure_ascii=False),
                "score_json": json.dumps(scores, ensure_ascii=False), "contribution_json": json.dumps(contributions, ensure_ascii=False),
                "model_score": _json_value(row.get("model_score")), "coverage": _json_value(row.get("factor_coverage")),
                "quality_flag": row.get("quality_flag"),
                "next_month_end": pd.Timestamp(forward_row.next_month_end).date().isoformat() if forward_row is not None and pd.notna(forward_row.next_month_end) else None,
                "forward_return": _json_value(forward_row.forward_return) if forward_row is not None else None,
            })
            if pd.notna(row.get("factor_coverage")):
                coverage_values.append(float(row["factor_coverage"]))
        with connect(path) as conn:
            upsert_rows(conn, "monthly_features", stored)
        if progress:
            progress(index, len(months), month)
    with connect(path) as conn:
        conn.execute(
            "UPDATE experiments SET status = 'features_ready', coverage = ? WHERE experiment_id = ?",
            (
                float(np.mean(coverage_values)) if coverage_values else None,
                experiment_id,
            ),
        )
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True)
    result["experiment_id"] = experiment_id
    return result


def available_experiments(path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    initialize_database(path)
    with connect(path) as conn:
        return pd.read_sql_query(
            """
            SELECT e.*
            FROM experiments e
            WHERE EXISTS (
              SELECT 1 FROM monthly_features f
              WHERE f.experiment_id = e.experiment_id
            )
            ORDER BY e.created_at DESC
            """,
            conn,
        )


def available_feature_models(path: str | Path = DEFAULT_DB_PATH) -> list[str]:
    experiments = available_experiments(path)
    if experiments.empty:
        return []
    available = set(experiments["model_name"].dropna().astype(str))
    return [name for name in MODEL_FACTOR_WEIGHTS if name in available]


def load_feature_panel(
    path: str | Path = DEFAULT_DB_PATH,
    model_name: str = MODEL_FULL_13,
    experiment_id: str | None = None,
    latest_only: bool = False,
) -> pd.DataFrame:
    if experiment_id is None:
        experiments = available_experiments(path)
        matching = experiments[experiments["model_name"] == model_name]
        if matching.empty:
            return pd.DataFrame()
        experiment_id = str(matching.iloc[0]["experiment_id"])
    filters: dict[str, object] = {"experiment_id": experiment_id}
    if latest_only:
        initialize_database(path)
        with connect(path) as conn:
            latest = conn.execute(
                "SELECT MAX(month_end) FROM monthly_features WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()[0]
        if latest is None:
            return pd.DataFrame()
        filters["month_end"] = latest
    features = read_table("monthly_features", path, filters=filters)
    if features.empty:
        return features
    securities = read_table(
        "security_master", path, columns=["symbol", "name", "sector"]
    )
    expanded = []
    for row in features.itertuples(index=False):
        payload = {
            "model_name": row.model_name,
            "experiment_id": row.experiment_id,
            "month_end": pd.Timestamp(row.month_end),
            "symbol": row.symbol,
            "model_score": row.model_score,
            "factor_coverage": row.coverage,
            "quality_flag": row.quality_flag,
            "forward_return": row.forward_return,
            "next_month_end": row.next_month_end,
        }
        payload.update(json.loads(row.raw_json or "{}"))
        scores = json.loads(row.score_json or "{}")
        payload.update({f"{key}__score": value for key, value in scores.items()})
        expanded.append(payload)
    panel = pd.DataFrame(expanded)
    if not securities.empty:
        panel = panel.merge(securities[["symbol", "name", "sector"]], on="symbol", how="left")
    return panel


def backtest_from_panel(
    panel: pd.DataFrame,
    mode: str = "enhanced",
    top_n: int = 30,
    method: str = "blend",
    transaction_cost: float = 0.001,
    settings: dict | None = None,
    start_date=None,
):
    source = panel.copy()
    if start_date is not None:
        source = source[pd.to_datetime(source["month_end"]) >= pd.Timestamp(start_date)].copy()
    holdings = []
    for month, group in source.groupby("month_end"):
        available = group.dropna(subset=["forward_return"])
        if available.empty:
            continue
        portfolio = build_enhanced_portfolio(available, top_n, method, settings) if mode == "enhanced" else build_article_baseline(available, top_n, settings)
        portfolio["month_end"] = pd.Timestamp(month)
        holdings.append(portfolio)
    all_holdings = pd.concat(holdings, ignore_index=True) if holdings else pd.DataFrame()
    return run_monthly_backtest(all_holdings, transaction_cost) if not all_holdings.empty else (pd.DataFrame(), pd.DataFrame())


def _json_value(value):
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
