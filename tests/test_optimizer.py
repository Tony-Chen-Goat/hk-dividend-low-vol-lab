import math

from app.config import MODEL_YAHOO_10, YAHOO_FACTOR_WEIGHTS
from app.optimizer import experiment_score, group_weight_candidates, sampled_weight_candidates


def test_group_weight_candidates_are_valid():
    candidates = group_weight_candidates()
    assert candidates
    assert all(math.isclose(sum(item.values()), 1.0) for item in candidates)
    assert all(0.30 <= item["红利"] <= 0.50 for item in candidates)


def test_sampled_candidates_include_baseline_and_limit():
    candidates = sampled_weight_candidates(5)
    assert len(candidates) == 5
    assert math.isclose(sum(candidates[0].values()), 1.0)


def test_yahoo_candidates_use_only_ten_available_factors():
    candidates = sampled_weight_candidates(5, model_name=MODEL_YAHOO_10)
    assert len(candidates) == 5
    assert set(candidates[0]) == set(YAHOO_FACTOR_WEIGHTS)
    assert all(math.isclose(sum(item.values()), 1.0) for item in candidates)


def test_experiment_score_formula():
    assert math.isclose(experiment_score(1.0, 0.5, 0.2, 0.3), 1.09)
