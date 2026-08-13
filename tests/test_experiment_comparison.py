import pandas as pd

from app.experiment_comparison import (
    common_period_curves,
    comparison_analysis,
    configuration_comparison,
    core_metric_comparison,
    factor_weight_comparison,
)


def records():
    record_a = {
        "model_name": "yahoo_10",
        "coverage": 0.95,
        "factor_weights": {"dividend_yield_3y": 0.6, "volatility_60d": 0.4},
        "backtest_settings": {"selected_count": 10, "dividend_pct": 50, "inverse_volatility_pct": 50, "max_stock_weight": 0.05, "transaction_cost": 0.001},
        "metrics": {
            "annualized_return": 0.10, "annualized_volatility": 0.12,
            "sharpe": 0.8, "max_drawdown": 0.15, "calmar": 0.67,
            "average_turnover": 0.10, "rank_icir": 0.20,
            "positive_ratio": 0.55, "information_ratio": 0.3,
            "gross_total_return": 0.50, "net_total_return": 0.45,
        },
    }
    record_b = {
        "model_name": "yahoo_10",
        "coverage": 0.90,
        "factor_weights": {"dividend_yield_3y": 0.4, "volatility_60d": 0.6},
        "backtest_settings": {"selected_count": 5, "dividend_pct": 30, "inverse_volatility_pct": 70, "max_stock_weight": 0.10, "transaction_cost": 0.001},
        "metrics": {
            "annualized_return": 0.14, "annualized_volatility": 0.18,
            "sharpe": 0.7, "max_drawdown": 0.22, "calmar": 0.64,
            "average_turnover": 0.18, "rank_icir": 0.30,
            "positive_ratio": 0.58, "information_ratio": 0.4,
            "gross_total_return": 0.70, "net_total_return": 0.60,
        },
    }
    return record_a, record_b


def test_core_metrics_respect_higher_and_lower_is_better():
    record_a, record_b = records()
    display, raw = core_metric_comparison(record_a, record_b)
    winners = raw.set_index("key")["preferred"].to_dict()

    assert winners["annualized_return"] == "实验B"
    assert winners["annualized_volatility"] == "实验A"
    assert winners["max_drawdown"] == "实验A"
    assert winners["average_turnover"] == "实验A"
    assert display.loc[display["指标"] == "年化收益", "实验B"].iloc[0] == "14.0%"


def test_configuration_and_factor_comparison_are_complete():
    record_a, record_b = records()
    config_display, _ = configuration_comparison(record_a, record_b)
    weight_display, _ = factor_weight_comparison(record_a, record_b)

    assert "每月入选数量" in config_display["配置"].tolist()
    assert "三年平均股息率" in weight_display["因子"].tolist()


def test_common_period_rebases_both_experiments_and_builds_analysis():
    backtests = pd.DataFrame({
        "experiment_id": ["A", "A", "A", "B", "B", "B"],
        "month_end": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"] * 2),
        "net_return": [0.10, 0.00, -0.05, 0.00, 0.05, 0.02],
    })
    curves = common_period_curves(backtests, "A", "B")
    record_a, record_b = records()
    _, raw = core_metric_comparison(record_a, record_b)
    analysis = comparison_analysis(raw, curves)

    assert curves["实验A净值"].iloc[0] == 1.1
    assert curves["实验B净值"].iloc[0] == 1.0
    assert curves["实验A回撤"].min() < 0
    assert any("公平区间" in detail for detail in analysis["details"])
