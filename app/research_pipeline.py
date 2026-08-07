from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import calculate_forward_returns, run_monthly_backtest
from .config import DEFAULT_DB_PATH, FACTOR_WEIGHTS
from .database import connect, initialize_database, read_table, upsert_rows
from .factors import calculate_monthly_features
from .portfolio import build_article_baseline, build_enhanced_portfolio
from .scoring import score_cross_section


def available_month_ends(prices: pd.DataFrame, minimum_history_days: int = 252) -> list[pd.Timestamp]:
    data = prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    unique = sorted(data["trade_date"].dropna().unique())
    if len(unique) < minimum_history_days:
        return []
    dates = pd.DatetimeIndex(unique[minimum_history_days - 1 :])
    return list(pd.Series(dates).groupby(dates.to_period("M")).max())


def compute_and_store_features(path: str | Path = DEFAULT_DB_PATH, weights: dict[str, float] | None = None, progress=None) -> pd.DataFrame:
    initialize_database(path)
    prices = read_table("daily_prices", path)
    dividends = read_table("dividends", path)
    fundamentals = read_table("fundamentals", path)
    securities = read_table("security_master", path)
    if prices.empty:
        return pd.DataFrame()
    rows, stored = [], []
    months = available_month_ends(prices)
    for index, month in enumerate(months, start=1):
        raw = calculate_monthly_features(prices, dividends, fundamentals, month)
        if raw.empty:
            continue
        if not securities.empty:
            raw = raw.merge(securities[["symbol", "sector"]], on="symbol", how="left")
        scored = score_cross_section(raw, weights or dict(FACTOR_WEIGHTS))
        rows.append(scored)
        for _, row in scored.iterrows():
            raw_values = {factor: _json_value(row.get(factor)) for factor in FACTOR_WEIGHTS}
            wins = {factor: _json_value(row.get(f"{factor}__winsorized")) for factor in FACTOR_WEIGHTS}
            scores = {factor: _json_value(row.get(f"{factor}__score")) for factor in FACTOR_WEIGHTS}
            contributions = {factor: _json_value(row.get(f"{factor}__contribution")) for factor in FACTOR_WEIGHTS}
            stored.append({
                "month_end": pd.Timestamp(month).date().isoformat(), "symbol": row["symbol"],
                "raw_json": json.dumps(raw_values, ensure_ascii=False), "winsorized_json": json.dumps(wins, ensure_ascii=False),
                "score_json": json.dumps(scores, ensure_ascii=False), "contribution_json": json.dumps(contributions, ensure_ascii=False),
                "model_score": _json_value(row.get("model_score")), "coverage": _json_value(row.get("factor_coverage")),
                "quality_flag": row.get("quality_flag"),
            })
        if progress:
            progress(index, len(months), month)
    forward = calculate_forward_returns(prices)
    forward_rows = [
        {"month_end": pd.Timestamp(row.month_end).date().isoformat(), "symbol": row.symbol,
         "next_month_end": pd.Timestamp(row.next_month_end).date().isoformat() if pd.notna(row.next_month_end) else None,
         "forward_return": _json_value(row.forward_return)}
        for row in forward.itertuples()
    ]
    with connect(path) as conn:
        upsert_rows(conn, "monthly_features", stored)
        upsert_rows(conn, "forward_returns", forward_rows)
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True)
    return result.merge(forward, on=["symbol", "month_end"], how="left")


def load_feature_panel(path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    features = read_table("monthly_features", path)
    forward = read_table("forward_returns", path)
    securities = read_table("security_master", path)
    if features.empty:
        return features
    expanded = []
    for row in features.itertuples(index=False):
        payload = {"month_end": pd.Timestamp(row.month_end), "symbol": row.symbol, "model_score": row.model_score, "factor_coverage": row.coverage, "quality_flag": row.quality_flag}
        payload.update(json.loads(row.raw_json or "{}"))
        scores = json.loads(row.score_json or "{}")
        payload.update({f"{key}__score": value for key, value in scores.items()})
        expanded.append(payload)
    panel = pd.DataFrame(expanded)
    if not securities.empty:
        panel = panel.merge(securities[["symbol", "name", "sector"]], on="symbol", how="left")
    if not forward.empty:
        forward["month_end"] = pd.to_datetime(forward["month_end"])
        panel = panel.merge(forward[["symbol", "month_end", "forward_return", "next_month_end"]], on=["symbol", "month_end"], how="left")
    return panel


def backtest_from_panel(panel: pd.DataFrame, mode: str = "enhanced", top_n: int = 30, method: str = "blend", transaction_cost: float = 0.001, settings: dict | None = None):
    holdings = []
    for month, group in panel.groupby("month_end"):
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
