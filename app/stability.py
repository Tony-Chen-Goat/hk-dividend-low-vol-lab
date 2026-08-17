from __future__ import annotations

"""Compatibility helpers for Streamlit rolling deployments.

Streamlit can rerun a newly checked-out page while an older imported module is
still present in the Python process.  New pages must therefore not depend on a
new symbol being immediately available from an already-cached module.  These
helpers delegate to the current implementation after a cold start and provide
equivalent fallbacks during the short rolling-update window.
"""

import hashlib
import inspect
import json
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from . import database as database_module
from . import universe as universe_module
from .config import DEFAULT_DB_PATH, UNIVERSE_COLUMNS


def _canonical_value(value):
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _stable_frame_fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    selected = [column for column in columns if column in frame]
    records = []
    if selected:
        ordered = frame[selected].copy()
        sort_columns = [column for column in ["symbol", "trade_date", "report_period"] if column in ordered]
        if sort_columns:
            ordered = ordered.sort_values(sort_columns, kind="stable", na_position="last")
        records = [
            {column: _canonical_value(row.get(column)) for column in selected}
            for row in ordered.to_dict("records")
        ]
    encoded = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def universe_fingerprint(frame: pd.DataFrame) -> str:
    implementation = getattr(universe_module, "universe_fingerprint", None)
    if callable(implementation):
        return implementation(frame)
    return _stable_frame_fingerprint(frame, UNIVERSE_COLUMNS)


def risk_snapshot_fingerprint(
    snapshot: pd.DataFrame,
    settings: Mapping[str, float | int | bool],
    *,
    as_of=None,
    universe_version: str | None = None,
) -> str:
    implementation = getattr(universe_module, "risk_snapshot_fingerprint", None)
    if callable(implementation):
        return implementation(
            snapshot, settings, as_of=as_of, universe_version=universe_version,
        )
    columns = [
        "symbol", "security_type", "board", "listing_days", "last_trade_date",
        "close", "valid_trading_ratio_60d", "max_suspension_days",
        "avg_traded_value_20d", "free_float_market_cap",
        "stopped_dividend_1y", "dividend_cut", "inactive_event_effective",
    ]
    payload = {
        "as_of": str(pd.Timestamp(as_of).date()) if as_of is not None else None,
        "universe_version": universe_version,
        "settings": {str(key): _canonical_value(value) for key, value in sorted(settings.items())},
        "snapshot": _stable_frame_fingerprint(snapshot, columns),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def resolve_stock_data_cutoff(
    path: str | Path = DEFAULT_DB_PATH,
    symbols: Iterable[str] | None = None,
) -> dict:
    implementation = getattr(database_module, "resolve_stock_data_cutoff", None)
    if callable(implementation):
        return implementation(path, symbols)
    requested = sorted({str(symbol) for symbol in (symbols or []) if symbol})
    clauses = ["symbol NOT LIKE '^%'"]
    params: list[object] = []
    if requested:
        clauses.append(f"symbol IN ({','.join('?' for _ in requested)})")
        params.extend(requested)
    database_module.initialize_database(path)
    with database_module.connect(path) as conn:
        rows = conn.execute(
            f"""
            SELECT latest_date, COUNT(*) AS symbol_count
            FROM (
              SELECT symbol, MAX(trade_date) AS latest_date
              FROM daily_prices
              WHERE {' AND '.join(clauses)}
              GROUP BY symbol
            )
            WHERE latest_date IS NOT NULL
            GROUP BY latest_date
            ORDER BY symbol_count DESC, latest_date DESC
            """,
            params,
        ).fetchall()
        available = conn.execute(
            f"SELECT COUNT(DISTINCT symbol) FROM daily_prices WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()[0]
    return {
        "as_of": str(rows[0][0]) if rows else None,
        "aligned_symbols": int(rows[0][1]) if rows else 0,
        "available_symbols": int(available or 0),
        "requested_symbols": len(requested),
    }


def read_recent_stock_prices(
    path: str | Path = DEFAULT_DB_PATH,
    lookback: int = 60,
    *,
    symbols: Iterable[str] | None = None,
    as_of=None,
) -> pd.DataFrame:
    """Call either the new scoped reader or the old reader plus local filters."""
    implementation = database_module.read_recent_stock_prices
    parameters = inspect.signature(implementation).parameters
    if "symbols" in parameters and "as_of" in parameters:
        return implementation(path, lookback, symbols=symbols, as_of=as_of)
    frame = implementation(path, lookback)
    requested = {str(symbol) for symbol in (symbols or []) if symbol}
    if requested and not frame.empty:
        frame = frame[frame["symbol"].astype(str).isin(requested)].copy()
    if as_of is not None and not frame.empty:
        cutoff = pd.Timestamp(as_of)
        frame = frame[pd.to_datetime(frame["trade_date"], errors="coerce") <= cutoff].copy()
    return frame.sort_values(["symbol", "trade_date"], kind="stable") if not frame.empty else frame
