from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import DEFAULT_DB_PATH
from .database import connect, initialize_database


def coverage_ratio(frame: pd.DataFrame, columns: list[str]) -> float:
    if frame.empty or not columns:
        return 0.0
    existing = [column for column in columns if column in frame]
    return float(frame[existing].notna().all(axis=1).mean()) if existing else 0.0


def database_quality_snapshot(path: str | Path = DEFAULT_DB_PATH) -> dict:
    initialize_database(path)
    with connect(path) as conn:
        prices = pd.read_sql_query("SELECT symbol, trade_date, close, adjusted_close, volume FROM daily_prices", conn)
        dividends = pd.read_sql_query("SELECT symbol, ex_date, dividend_per_share FROM dividends", conn)
        fundamentals = pd.read_sql_query("SELECT symbol, published_date, payout_ratio, free_float_shares FROM fundamentals", conn)
        securities = pd.read_sql_query("SELECT symbol, effective_date, end_date, source FROM security_master", conn)
    latest = pd.to_datetime(prices["trade_date"], errors="coerce").max() if not prices.empty else pd.NaT
    symbols = securities["symbol"].nunique() if not securities.empty else 0
    price_symbols = prices["symbol"].nunique() if not prices.empty else 0
    dividend_symbols = dividends["symbol"].nunique() if not dividends.empty else 0
    fundamental_symbols = fundamentals["symbol"].nunique() if not fundamentals.empty else 0
    historical = False
    if not securities.empty:
        historical = securities["effective_date"].notna().any() and securities["end_date"].notna().any()
    denominator = symbols or 1
    return {
        "data_cutoff": latest,
        "price_coverage": price_symbols / denominator,
        "dividend_coverage": dividend_symbols / denominator,
        "fundamental_coverage": fundamental_symbols / denominator,
        "free_float_coverage": coverage_ratio(fundamentals, ["free_float_shares"]),
        "historical_membership_coverage": 1.0 if historical else 0.0,
        "survivor_bias": bool(symbols and not historical),
        "current_constituents_backfill": bool(symbols and not historical),
        "missing_announcement_dates": bool(not fundamentals.empty and fundamentals["published_date"].isna().any()),
        "disabled_factors": [] if not fundamentals.empty else ["股息支付率可持续性", "现金流覆盖能力", "流通市值"],
        "quality_note": "本测试使用当前指数成分股回溯历史，可能存在幸存者偏差。" if symbols and not historical else "",
    }
