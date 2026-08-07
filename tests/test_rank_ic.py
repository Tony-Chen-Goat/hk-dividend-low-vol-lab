import numpy as np
import pandas as pd

from app.rank_ic import ic_summary, monthly_rank_ic, rank_ic


def test_rank_ic_perfect_monotonic():
    assert np.isclose(rank_ic(pd.Series([1, 2, 3, 4, 5]), pd.Series([2, 4, 6, 8, 10])), 1)


def test_rank_ic_uses_all_valid_and_skips_small_sample():
    value = rank_ic(pd.Series([1, 2, 3]), pd.Series([3, 2, 1]), min_observations=5)
    assert np.isnan(value)


def test_monthly_rank_ic_and_summary():
    frame = pd.DataFrame({
        "month_end": ["2024-01-31"] * 5 + ["2024-02-29"] * 5,
        "model_score": list(range(5)) * 2,
        "forward_return": list(range(5)) + list(range(4, -1, -1)),
    })
    monthly = monthly_rank_ic(frame)
    assert np.allclose(monthly["rank_ic"].tolist(), [1.0, -1.0])
    summary = ic_summary(monthly)
    assert summary["mean_rank_ic"] == 0
    assert summary["positive_ratio"] == 0.5
