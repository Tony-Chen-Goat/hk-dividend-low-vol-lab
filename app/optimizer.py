from __future__ import annotations

import itertools
import random
from collections.abc import Callable, Iterator

from .config import FACTOR_GROUPS, FACTOR_WEIGHTS


def group_weight_candidates(step: float = 0.05) -> list[dict[str, float]]:
    dividends = _float_range(0.30, 0.50, step)
    low_vols = _float_range(0.30, 0.50, step)
    others = _float_range(0.15, 0.30, step)
    return [
        {"红利": d, "低波": v, "质量/流动性/规模": o}
        for d, v, o in itertools.product(dividends, low_vols, others)
        if abs(d + v + o - 1) < 1e-9
    ]


def _float_range(start: float, stop: float, step: float) -> list[float]:
    count = round((stop - start) / step)
    return [round(start + index * step, 10) for index in range(count + 1)]


def rescale_within_groups(group_weights: dict[str, float]) -> dict[str, float]:
    output = {}
    for group, factors in FACTOR_GROUPS.items():
        baseline = sum(FACTOR_WEIGHTS[factor] for factor in factors)
        for factor in factors:
            output[factor] = FACTOR_WEIGHTS[factor] / baseline * group_weights[group]
    return output


def sampled_weight_candidates(max_experiments: int = 50, seed: int = 7) -> list[dict[str, float]]:
    candidates = [rescale_within_groups(item) for item in group_weight_candidates()]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return [dict(FACTOR_WEIGHTS)] + candidates[: max(0, max_experiments - 1)]


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
