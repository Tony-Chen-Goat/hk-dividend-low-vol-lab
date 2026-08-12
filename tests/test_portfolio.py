import math

import pandas as pd

from app.portfolio import apply_portfolio_constraints, portfolio_turnover, raw_portfolio_weights


def sample():
    return pd.DataFrame({
        "symbol": [f"S{i}" for i in range(8)],
        "sector": ["金融"] * 4 + ["科技"] * 4,
        "dividend_yield_ttm": [0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01],
        "volatility_60d": [0.2] * 8,
    })


def test_raw_weight_methods_sum_to_one():
    frame = sample()
    for method in ["dividend", "inverse_volatility", "blend"]:
        assert math.isclose(raw_portfolio_weights(frame, method).sum(), 1.0)


def test_custom_dividend_inverse_volatility_mix_changes_weights():
    frame = sample()
    dividend_heavy = raw_portfolio_weights(frame, "blend", dividend_mix=0.8)
    volatility_heavy = raw_portfolio_weights(frame, "blend", dividend_mix=0.2)
    assert math.isclose(dividend_heavy.sum(), 1.0)
    assert dividend_heavy.iloc[0] > volatility_heavy.iloc[0]


def test_stock_and_sector_caps_and_cash_retention():
    frame = sample()
    constrained = apply_portfolio_constraints(frame, raw_portfolio_weights(frame), {"max_stock_weight": 0.10, "max_sector_weight": 0.25, "max_top5_weight": 0.40, "min_stock_weight": 0.01})
    assert constrained["target_weight"].max() <= 0.10 + 1e-12
    assert constrained.groupby("sector")["target_weight"].sum().max() <= 0.25 + 1e-12
    assert math.isclose(constrained["target_weight"].sum() + constrained["cash_weight"].sum(), 1.0)
    assert constrained["cash_weight"].sum() > 0


def test_turnover():
    previous = pd.Series({"A": 0.5, "B": 0.5})
    current = pd.Series({"A": 0.25, "C": 0.75})
    assert portfolio_turnover(previous, current) == 0.75
