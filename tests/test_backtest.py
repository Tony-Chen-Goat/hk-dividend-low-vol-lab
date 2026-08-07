import math

import pandas as pd

from app.backtest import calculate_forward_returns, expanding_walk_forward_splits, performance_metrics, run_monthly_backtest


def test_next_month_return_alignment():
    prices = pd.DataFrame({
        "symbol": ["0700.HK"] * 3,
        "trade_date": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-28"]),
        "adjusted_close": [100.0, 110.0, 99.0],
    })
    result = calculate_forward_returns(prices)
    assert math.isclose(result.iloc[0]["forward_return"], 0.1)
    assert math.isclose(result.iloc[1]["forward_return"], -0.1)
    assert pd.isna(result.iloc[2]["forward_return"])


def test_month_end_rebalance_and_transaction_cost():
    holdings = pd.DataFrame({
        "month_end": pd.to_datetime(["2024-01-31", "2024-02-29"]),
        "symbol": ["A", "A"], "target_weight": [0.5, 0.5], "forward_return": [0.1, -0.1],
    })
    monthly, detail = run_monthly_backtest(holdings, transaction_cost=0.01)
    assert monthly.iloc[0]["turnover"] == 0.25
    assert monthly.iloc[0]["net_return"] < monthly.iloc[0]["gross_return"]
    assert len(detail) == 2


def test_performance_metrics():
    monthly = pd.DataFrame({"net_return": [0.02, -0.01, 0.03], "gross_return": [0.021, -0.009, 0.031], "turnover": [0.2, 0.1, 0.3]})
    metrics = performance_metrics(monthly)
    assert metrics["net_total_return"] > 0
    assert metrics["max_drawdown"] >= 0
    assert math.isclose(metrics["average_turnover"], 0.2)


def test_expanding_in_sample_out_of_sample_split_has_no_overlap():
    months = pd.date_range("2018-01-31", periods=84, freq="ME")
    splits = expanding_walk_forward_splits(months, train_years=5, validation_months=12)
    assert len(splits) == 2
    for train, validation in splits:
        assert train.max() < validation.min()
        assert not set(train).intersection(validation)
