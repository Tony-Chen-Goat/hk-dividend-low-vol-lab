from __future__ import annotations

import itertools
import random
from collections.abc import Callable, Iterator

from .config import (
    MODEL_FACTOR_GROUPS,
    MODEL_FACTOR_WEIGHTS,
    MODEL_FULL_13,
    MODEL_YAHOO_10,
)


def group_weight_candidates(step: float = 0.05, model_name: str = MODEL_FULL_13) -> list[dict[str, float]]:
    if model_name == MODEL_YAHOO_10:
        dividends = _float_range(0.40, 0.55, step)
        low_vols = _float_range(0.40, 0.55, step)
        others = _float_range(0.05, 0.15, step)
        other_label = "流动性"
    else:
        dividends = _float_range(0.30, 0.50, step)
        low_vols = _float_range(0.30, 0.50, step)
        others = _float_range(0.15, 0.30, step)
        other_label = "质量/流动性/规模"
    return [
        {"红利": d, "低波": v, other_label: o}
        for d, v, o in itertools.product(dividends, low_vols, others)
        if abs(d + v + o - 1) < 1e-9
    ]


def _float_range(start: float, stop: float, step: float) -> list[float]:
    count = round((stop - start) / step)
    return [round(start + index * step, 10) for index in range(count + 1)]


def rescale_within_groups(
    group_weights: dict[str, float],
    model_name: str = MODEL_FULL_13,
) -> dict[str, float]:
    factor_groups = MODEL_FACTOR_GROUPS[model_name]
    factor_weights = MODEL_FACTOR_WEIGHTS[model_name]
    output = {}
    for group, factors in factor_groups.items():
        baseline = sum(factor_weights[factor] for factor in factors)
        for factor in factors:
            output[factor] = factor_weights[factor] / baseline * group_weights[group]
    return output


def sampled_weight_candidates(
    max_experiments: int = 50,
    seed: int = 7,
    model_name: str = MODEL_FULL_13,
) -> list[dict[str, float]]:
    candidates = [
        rescale_within_groups(item, model_name)
        for item in group_weight_candidates(model_name=model_name)
    ]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return [dict(MODEL_FACTOR_WEIGHTS[model_name])] + candidates[: max(0, max_experiments - 1)]


def experiment_score(rank_icir: float, information_ratio: float, max_drawdown: float, average_turnover: float, coefficients=(1.0, 0.5, 0.5, 0.2)) -> float:
    a, b, c, d = coefficients
    return float(a * rank_icir + b * information_ratio - c * abs(max_drawdown) - d * average_turnover)


def run_optimizer(candidates: list[dict[str, float]], evaluator: Callable[[dict[str, float]], dict], cancelled: Callable[[], bool] | None = None, progress: Callable[[int, int, dict], None] | None = None) -> list[dict]:
    results = []
    for index, weights in enumerate(candidates, start=1):
        if cancelled and cancelled():
            break
        metrics = evaluator(weights)
        result = {"weights": weights, **metrics}
        results.append(result)
        if progress:
            progress(index, len(candidates), result)
    return results
