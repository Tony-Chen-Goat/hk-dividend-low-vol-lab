from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def rank_ic(scores: pd.Series, forward_returns: pd.Series, min_observations: int = 5) -> float:
    aligned = pd.concat([scores.rename("score"), forward_returns.rename("return")], axis=1).dropna()
    if len(aligned) < min_observations or aligned["score"].nunique() < 2 or aligned["return"].nunique() < 2:
        return np.nan
    return float(spearmanr(aligned["score"], aligned["return"]).statistic)


def monthly_rank_ic(frame: pd.DataFrame, score_column: str = "model_score", return_column: str = "forward_return", min_observations: int = 5) -> pd.DataFrame:
    records = []
    for month, group in frame.groupby("month_end"):
        value = rank_ic(group[score_column], group[return_column], min_observations)
        records.append({
            "month_end": pd.Timestamp(month), "rank_ic": value,
            "valid_count": int(group[[score_column, return_column]].dropna().shape[0]),
            "skip_reason": "有效股票太少或横截面无变化" if pd.isna(value) else None,
        })
    result = pd.DataFrame(records).sort_values("month_end") if records else pd.DataFrame(columns=["month_end", "rank_ic", "valid_count", "skip_reason"])
    if not result.empty:
        result["cumulative_rank_ic"] = result["rank_ic"].fillna(0).cumsum()
        result["rolling_12m_ic"] = result["rank_ic"].rolling(12, min_periods=3).mean()
    return result


def ic_summary(monthly: pd.DataFrame) -> dict[str, float]:
    values = monthly.get("rank_ic", pd.Series(dtype=float)).dropna()
    if values.empty:
        return {key: np.nan for key in ["mean_rank_ic", "rank_ic_std", "positive_ratio", "rank_icir", "annualized_rank_icir", "latest_12m_rank_ic"]}
    mean = float(values.mean())
    std = float(values.std(ddof=1)) if len(values) > 1 else np.nan
    icir = mean / std if std and not pd.isna(std) else np.nan
    return {
        "mean_rank_ic": mean,
        "rank_ic_std": std,
        "positive_ratio": float((values > 0).mean()),
        "rank_icir": icir,
        "annualized_rank_icir": icir * math.sqrt(12) if pd.notna(icir) else np.nan,
        "latest_12m_rank_ic": float(values.tail(12).mean()),
    }


def compare_factor_ics(frame: pd.DataFrame, factors: list[str], return_column: str = "forward_return") -> pd.DataFrame:
    rows = []
    for factor in factors:
        monthly = monthly_rank_ic(frame, factor, return_column)
        summary = ic_summary(monthly)
        rows.append({"factor": factor, **summary})
    return pd.DataFrame(rows)
