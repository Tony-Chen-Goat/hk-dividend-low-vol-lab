from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FACTOR_WEIGHTS, LOWER_IS_BETTER


def validate_weights(weights: dict[str, float], tolerance: float = 1e-9) -> tuple[bool, float]:
    total = float(sum(weights.values()))
    return abs(total - 1.0) <= tolerance, 1.0 - total


def winsorize_series(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() < 2:
        return numeric
    return numeric.clip(numeric.quantile(lower), numeric.quantile(upper))


def percentile_score(series: pd.Series, lower_is_better: bool = False) -> pd.Series:
    score = pd.to_numeric(series, errors="coerce").rank(method="average", pct=True) * 100
    return 100 - score + (100 / score.notna().sum() if score.notna().sum() else 0) if lower_is_better else score


def score_cross_section(features: pd.DataFrame, weights: dict[str, float] | None = None, by_sector: bool = False) -> pd.DataFrame:
    weights = weights or dict(FACTOR_WEIGHTS)
    valid, delta = validate_weights(weights)
    if not valid:
        action = "增加" if delta > 0 else "减少"
        raise ValueError(f"因子权重必须等于100%，当前需{action}{abs(delta):.1%}")
    data = features.copy()
    if "dividend_stability" not in data:
        components = data[["consecutive_dividend_years", "dividend_cv", "no_large_dividend_cut"]].copy()
        components["years_score"] = percentile_score(components["consecutive_dividend_years"])
        components["cv_score"] = percentile_score(components["dividend_cv"], lower_is_better=True)
        data["dividend_stability"] = components["years_score"] * 0.5 + components["cv_score"] * 0.3 + components["no_large_dividend_cut"] * 100 * 0.2
    contributions = []
    for factor, weight in weights.items():
        winsorized = f"{factor}__winsorized"
        score = f"{factor}__score"
        data[winsorized] = winsorize_series(data.get(factor, pd.Series(index=data.index, dtype=float)))
        if factor == "payout_sustainability":
            data[score] = data[winsorized]
        elif by_sector and "sector" in data:
            data[score] = data.groupby("sector", dropna=False)[winsorized].transform(lambda x: percentile_score(x, factor in LOWER_IS_BETTER))
        else:
            data[score] = percentile_score(data[winsorized], factor in LOWER_IS_BETTER)
        contribution = f"{factor}__contribution"
        data[contribution] = data[score] * weight
        contributions.append(contribution)
    data["model_score"] = data[contributions].sum(axis=1, min_count=len(contributions))
    data["factor_coverage"] = data[[f"{name}__score" for name in weights]].notna().mean(axis=1)
    data["quality_flag"] = np.where(data["factor_coverage"] == 1, "完整", "数据不足")
    return data
