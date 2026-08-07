from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from .config import RISK_DEFAULTS, UNIVERSE_COLUMNS
from .yahoo_provider import normalize_hk_symbol


EXCLUDED_TYPES = {"ETF", "REIT", "SPAC", "Warrant", "CBBC", "Preferred Stock", "Structured Product"}


def validate_universe_csv(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in UNIVERSE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"证券池 CSV 缺少列: {', '.join(missing)}")
    result = frame[UNIVERSE_COLUMNS].copy()
    result["raw_symbol"] = result["symbol"].astype(str)
    normalized = []
    errors = []
    for value in result["symbol"]:
        try:
            normalized.append(normalize_hk_symbol(value))
            errors.append(None)
        except ValueError as exc:
            normalized.append(None)
            errors.append(str(exc))
    result["symbol"] = normalized
    result["symbol_error"] = errors
    result["effective_date"] = pd.to_datetime(result["effective_date"], errors="coerce")
    result["end_date"] = pd.to_datetime(result["end_date"], errors="coerce")
    return result


def universe_at_date(frame: pd.DataFrame, as_of) -> pd.DataFrame:
    date = pd.Timestamp(as_of)
    data = frame.copy()
    effective = pd.to_datetime(data["effective_date"], errors="coerce")
    ended = pd.to_datetime(data["end_date"], errors="coerce")
    mask = (effective.isna() | (effective <= date)) & (ended.isna() | (ended >= date))
    return data.loc[mask].copy()


@dataclass
class FilterResult:
    included: pd.DataFrame
    excluded: pd.DataFrame


def apply_hk_risk_filters(
    snapshot: pd.DataFrame, settings: Mapping[str, float | int | bool] | None = None,
) -> FilterResult:
    cfg = {**RISK_DEFAULTS, **(settings or {})}
    rows = []
    for _, row in snapshot.iterrows():
        reasons: list[str] = []
        security_type = str(row.get("security_type", ""))
        board = str(row.get("board", ""))
        if cfg.get("main_board_only", True) and board and board.lower() not in {"main board", "main", "主板"}:
            reasons.append("非港交所主板")
        if cfg.get("exclude_gem", True) and board.upper() == "GEM":
            reasons.append("GEM")
        if security_type in EXCLUDED_TYPES:
            reasons.append(f"不支持的证券类型: {security_type}")
        if pd.notna(row.get("listing_days")) and row.get("listing_days") < cfg["min_listing_days"]:
            reasons.append(f"上市不足{cfg['min_listing_days']}个交易日")
        if pd.isna(row.get("close")) or row.get("close") < cfg["min_price_hkd"]:
            reasons.append(f"股价低于{cfg['min_price_hkd']:g}港元或缺失")
        if pd.isna(row.get("valid_trading_ratio_60d")) or row.get("valid_trading_ratio_60d") < cfg["min_valid_trading_ratio_60d"]:
            reasons.append("60日有效交易比例不足")
        if row.get("max_suspension_days", 0) > cfg["max_suspension_days"]:
            reasons.append("连续停牌日数超限")
        if bool(row.get("stopped_dividend_1y", False)):
            reasons.append("最近一年停止派息")
        if pd.notna(row.get("dividend_cut")) and row.get("dividend_cut") > cfg["max_dividend_cut"]:
            reasons.append("最近一年股息削减超限")
        if pd.isna(row.get("avg_traded_value_20d")) or row.get("avg_traded_value_20d") < cfg["min_avg_traded_value_20d"]:
            reasons.append("20日平均成交额不足")
        if pd.isna(row.get("free_float_market_cap")) or row.get("free_float_market_cap") < cfg["min_free_float_market_cap"]:
            reasons.append("自由流通市值不足或缺失")
        if bool(row.get("inactive_event_effective", False)):
            reasons.append("退市/清盘/私有化/长期停牌信息已生效")
        payload = row.to_dict()
        payload["included"] = not reasons
        payload["exclusion_reasons"] = "；".join(reasons)
        rows.append(payload)
    result = pd.DataFrame(rows)
    if result.empty:
        return FilterResult(result.copy(), result.copy())
    return FilterResult(result[result["included"]].copy(), result[~result["included"]].copy())


def build_risk_snapshot(prices: pd.DataFrame, securities: pd.DataFrame, fundamentals: pd.DataFrame | None = None) -> pd.DataFrame:
    data = prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    records = []
    for symbol, group in data.sort_values("trade_date").groupby("symbol"):
        tail60 = group.tail(60)
        tail20 = group.tail(20)
        valid = tail60["close"].notna() & tail60["volume"].fillna(0).gt(0)
        suspended = (~valid).astype(int)
        streaks = suspended.groupby((suspended != suspended.shift()).cumsum()).cumsum()
        records.append({
            "symbol": symbol,
            "listing_days": int(group["trade_date"].nunique()),
            "close": group.iloc[-1]["close"],
            "valid_trading_ratio_60d": float(valid.mean()) if len(tail60) else np.nan,
            "max_suspension_days": int(streaks.max()) if len(streaks) else 0,
            "avg_traded_value_20d": float((tail20["close"] * tail20["volume"]).mean()),
        })
    result = securities.merge(pd.DataFrame(records), on="symbol", how="left")
    if fundamentals is not None and not fundamentals.empty:
        latest = fundamentals.sort_values("report_period").groupby("symbol").tail(1)
        result = result.merge(latest[["symbol", "free_float_shares"]], on="symbol", how="left")
        result["free_float_market_cap"] = result["close"] * result["free_float_shares"]
    else:
        result["free_float_market_cap"] = np.nan
    return result
