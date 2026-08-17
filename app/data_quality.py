from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import DEFAULT_DB_PATH
from .database import connect, initialize_database, load_setting, resolve_stock_data_cutoff


def coverage_ratio(frame: pd.DataFrame, columns: list[str]) -> float:
    if frame.empty or not columns:
        return 0.0
    existing = [column for column in columns if column in frame]
    return float(frame[existing].notna().all(axis=1).mean()) if existing else 0.0


def database_quality_snapshot(path: str | Path = DEFAULT_DB_PATH) -> dict:
    initialize_database(path)
    active_universe = load_setting("active_universe", {}, path) or {}
    active_symbols = sorted({str(symbol) for symbol in active_universe.get("symbols", []) if symbol})
    symbol_clause = ""
    symbol_params: list[object] = []
    if active_symbols:
        symbol_clause = f" WHERE symbol IN ({','.join('?' for _ in active_symbols)})"
        symbol_params = list(active_symbols)
    with connect(path) as conn:
        latest, price_symbols = conn.execute(
            f"SELECT MAX(trade_date), COUNT(DISTINCT symbol) FROM daily_prices{symbol_clause}",
            symbol_params,
        ).fetchone()
        symbols = len(active_symbols) if active_symbols else conn.execute("SELECT COUNT(DISTINCT symbol) FROM security_master").fetchone()[0]
        dividend_symbols = conn.execute(
            f"SELECT COUNT(DISTINCT symbol) FROM dividends{symbol_clause}", symbol_params,
        ).fetchone()[0]
        fundamental_rows, fundamental_symbols, free_float_rows, missing_dates = conn.execute(
            f"""SELECT COUNT(*), COUNT(DISTINCT symbol),
                      SUM(CASE WHEN free_float_shares IS NOT NULL THEN 1 ELSE 0 END),
                      SUM(CASE WHEN published_date IS NULL THEN 1 ELSE 0 END)
               FROM fundamentals{symbol_clause}""",
            symbol_params,
        ).fetchone()
        effective_rows, ended_rows = conn.execute(
            f"""SELECT SUM(CASE WHEN effective_date IS NOT NULL THEN 1 ELSE 0 END),
                      SUM(CASE WHEN end_date IS NOT NULL THEN 1 ELSE 0 END)
               FROM security_master{symbol_clause}""",
            symbol_params,
        ).fetchone()
    cutoff_meta = resolve_stock_data_cutoff(path, active_symbols)
    latest = pd.to_datetime(cutoff_meta.get("as_of") or latest, errors="coerce")
    historical = bool(effective_rows and ended_rows)
    denominator = symbols or 1
    return {
        "data_cutoff": latest,
        "price_coverage": price_symbols / denominator,
        "dividend_coverage": dividend_symbols / denominator,
        "fundamental_coverage": fundamental_symbols / denominator,
        "free_float_coverage": float(free_float_rows or 0) / (fundamental_rows or 1),
        "historical_membership_coverage": 1.0 if historical else 0.0,
        "survivor_bias": bool(symbols and not historical),
        "current_constituents_backfill": bool(symbols and not historical),
        "missing_announcement_dates": bool(fundamental_rows and missing_dates),
        "disabled_factors": [] if fundamental_rows else ["股息支付率可持续性", "现金流覆盖能力", "流通市值"],
        "quality_note": "本测试使用当前指数成分股回溯历史，可能存在幸存者偏差。" if symbols and not historical else "",
    }
