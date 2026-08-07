from __future__ import annotations

import numpy as np
import pandas as pd

from .config import RISK_DEFAULTS


def raw_portfolio_weights(selected: pd.DataFrame, method: str = "blend") -> pd.Series:
    if selected.empty:
        return pd.Series(dtype=float)
    dividend = pd.to_numeric(selected["dividend_yield_ttm"], errors="coerce").clip(lower=0).fillna(0)
    volatility = pd.to_numeric(selected["volatility_60d"], errors="coerce").replace(0, np.nan)
    inverse_vol = (1 / volatility).replace([np.inf, -np.inf], np.nan).fillna(0)
    if method == "dividend":
        signal = dividend
    elif method == "inverse_volatility":
        signal = inverse_vol
    elif method == "blend":
        div_weight = dividend / dividend.sum() if dividend.sum() > 0 else pd.Series(0, index=selected.index)
        vol_weight = inverse_vol / inverse_vol.sum() if inverse_vol.sum() > 0 else pd.Series(0, index=selected.index)
        signal = div_weight * 0.5 + vol_weight * 0.5
    else:
        raise ValueError(f"未知组合加权方式: {method}")
    if signal.sum() <= 0:
        return pd.Series(0.0, index=selected.index)
    return signal / signal.sum()


def apply_portfolio_constraints(
    selected: pd.DataFrame, weights: pd.Series, settings: dict | None = None,
) -> pd.DataFrame:
    cfg = {**RISK_DEFAULTS, **(settings or {})}
    result = selected.copy()
    result["raw_weight"] = weights.reindex(result.index).fillna(0.0)
    result["target_weight"] = 0.0
    remaining = 1.0
    eligible = set(result.index)
    for _ in range(len(result) + 2):
        if remaining <= 1e-12 or not eligible:
            break
        signal = result.loc[list(eligible), "raw_weight"]
        if signal.sum() <= 0:
            break
        proposal = signal / signal.sum() * remaining
        changed = False
        for idx, value in proposal.items():
            capacity = cfg["max_stock_weight"] - result.at[idx, "target_weight"]
            add = min(float(value), max(capacity, 0))
            result.at[idx, "target_weight"] += add
            remaining -= add
            if add + 1e-12 < value or result.at[idx, "target_weight"] >= cfg["max_stock_weight"] - 1e-12:
                eligible.discard(idx)
                changed = True
        if not changed:
            break
    if "sector" in result:
        for sector, indexes in result.groupby("sector", dropna=False).groups.items():
            sector_weight = result.loc[indexes, "target_weight"].sum()
            if sector_weight > cfg["max_sector_weight"]:
                scale = cfg["max_sector_weight"] / sector_weight
                released = sector_weight - cfg["max_sector_weight"]
                result.loc[indexes, "target_weight"] *= scale
                remaining += released
    top5 = result["target_weight"].nlargest(5)
    if top5.sum() > cfg["max_top5_weight"]:
        scale = cfg["max_top5_weight"] / top5.sum()
        released = top5.sum() - cfg["max_top5_weight"]
        result.loc[top5.index, "target_weight"] *= scale
        remaining += released
    result.loc[result["target_weight"] < cfg["min_stock_weight"], "target_weight"] = 0.0
    invested = float(result["target_weight"].sum())
    result["cash_weight"] = 0.0
    if len(result):
        result.iloc[0, result.columns.get_loc("cash_weight")] = max(0.0, 1 - invested)
    result["constraint_note"] = np.where(result["target_weight"] > 0, "满足约束", "权重不足或受约束剔除")
    return result


def build_enhanced_portfolio(scored: pd.DataFrame, top_n: int = 30, method: str = "blend", settings: dict | None = None) -> pd.DataFrame:
    selected = scored.dropna(subset=["model_score"]).nlargest(top_n, "model_score").copy()
    return apply_portfolio_constraints(selected, raw_portfolio_weights(selected, method), settings)


def build_article_baseline(filtered: pd.DataFrame, top_n: int = 30, settings: dict | None = None) -> pd.DataFrame:
    required = ["dividend_yield_ttm", "volatility_60d", "avg_traded_value_20d", "free_float_market_cap"]
    selected = filtered.dropna(subset=required).sort_values(["volatility_60d", "dividend_yield_ttm"], ascending=[True, False]).head(top_n).copy()
    selected["model_score"] = np.nan
    return apply_portfolio_constraints(selected, raw_portfolio_weights(selected, "dividend"), settings)


def portfolio_turnover(previous: pd.Series, current: pd.Series) -> float:
    index = previous.index.union(current.index)
    return float((previous.reindex(index, fill_value=0) - current.reindex(index, fill_value=0)).abs().sum() / 2)
