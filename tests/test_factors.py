import math

import numpy as np
import pandas as pd

from app.config import YAHOO_FACTOR_WEIGHTS
from app.factors import (
    adjusted_returns, annualized_volatility, cashflow_coverage, daily_volatility_cv,
    dividend_growth_3y, dividend_stability_components, downside_volatility,
    max_drawdown, payout_sustainability_score, three_year_average_yield,
    ttm_dividend_yield,
)
from app.scoring import percentile_score, score_cross_section, validate_weights, winsorize_series


def dividend_frame():
    return pd.DataFrame({
        "ex_date": pd.to_datetime(["2021-06-01", "2022-06-01", "2023-06-01", "2024-06-01"]),
        "dividend_per_share": [1.0, 1.1, 1.21, 1.331],
    })


def test_adjusted_returns_do_not_add_dividends_again():
    result = adjusted_returns(pd.Series([100.0, 102.0]))
    assert math.isclose(result.iloc[1], 0.02)


def test_ttm_dividend_yield():
    assert math.isclose(ttm_dividend_yield(dividend_frame(), "2024-12-31", 20), 1.331 / 20)


def test_three_year_average_dividend_yield():
    result = three_year_average_yield(dividend_frame(), {2021: 10, 2022: 11, 2023: 12.1}, "2024-12-31")
    assert math.isclose(result, 0.1)


def test_three_year_average_requires_complete_data():
    assert np.isnan(three_year_average_yield(dividend_frame(), {2022: 11, 2023: 12}, "2024-12-31"))


def test_dividend_growth_and_stability():
    assert math.isclose(dividend_growth_3y(dividend_frame(), "2024-12-31"), 0.1)
    stability = dividend_stability_components(dividend_frame(), "2024-12-31")
    # 2024 is not a complete year at the 2024-12-31 signal definition;
    # stability uses the five complete years ending in 2023.
    assert stability["consecutive_years"] == 3
    assert stability["large_cut"] == 0


def test_volatility_downside_drawdown_and_cv():
    values = pd.Series(100 * np.cumprod(1 + np.tile([0.01, -0.005], 80)))
    expected = adjusted_returns(values).dropna().tail(60).std(ddof=1) * np.sqrt(252)
    assert math.isclose(annualized_volatility(values, 60), expected)
    assert downside_volatility(values, 60) >= 0
    assert 0 <= max_drawdown(values, 120) < 1
    assert daily_volatility_cv(values) >= 0


def test_insufficient_window_returns_nan():
    assert np.isnan(annualized_volatility(pd.Series([1, 2, 3]), 60))
    assert np.isnan(max_drawdown(pd.Series([1, 2, 3]), 120))


def test_payout_interval_score_and_cashflow():
    assert payout_sustainability_score(0.5) == 100
    assert math.isclose(payout_sustainability_score(0.8), 65)
    assert payout_sustainability_score(1.0) == 0
    assert payout_sustainability_score(0.5, -1) == 0
    assert cashflow_coverage(200, -100) == 2


def test_winsorize_and_reverse_percentile():
    values = pd.Series([1, 2, 3, 100])
    clipped = winsorize_series(values)
    assert clipped.max() < 100
    scores = percentile_score(pd.Series([1.0, 2.0, 3.0]), lower_is_better=True)
    assert scores.iloc[0] > scores.iloc[-1]


def test_weight_validation_and_cross_section_scoring():
    valid, delta = validate_weights({"a": 0.4, "b": 0.6})
    assert valid and abs(delta) < 1e-9
    features = pd.DataFrame({
        "x": [1.0, 2.0, 3.0], "consecutive_dividend_years": [1, 2, 3],
        "dividend_cv": [0.3, 0.2, 0.1], "no_large_dividend_cut": [0, 1, 1],
    })
    scored = score_cross_section(features, {"x": 1.0})
    assert scored["model_score"].is_monotonic_increasing


def test_yahoo_ten_factor_mode_does_not_require_fundamental_factors():
    features = pd.DataFrame({
        factor: [float(index + 1), float(index + 2), float(index + 3)]
        for index, factor in enumerate(YAHOO_FACTOR_WEIGHTS)
        if factor != "dividend_stability"
    })
    features["dividend_stability"] = [30.0, 60.0, 90.0]
    scored = score_cross_section(features, dict(YAHOO_FACTOR_WEIGHTS))
    assert scored["model_score"].notna().all()
    assert scored["factor_coverage"].eq(1.0).all()
