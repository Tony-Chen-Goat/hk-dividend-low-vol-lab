import math

import pandas as pd

from app.analysis import backtest_analysis, rank_ic_analysis


def test_rank_ic_analysis_explains_weak_positive_signal():
    monthly = pd.DataFrame({"rank_ic": [0.10, -0.05, 0.08, -0.01]})
    summary = {
        "mean_rank_ic": 0.03,
        "rank_icir": 0.1,
        "positive_ratio": 0.5,
        "latest_12m_rank_ic": 0.04,
    }
    result = rank_ic_analysis(summary, monthly)
    assert result["status"] == "信号偏弱，继续观察"
    assert "0.030" in result["summary"]


def test_backtest_analysis_reports_risk_and_benchmark():
    monthly = pd.DataFrame({"net_return": [0.02, -0.01, 0.03]})
    metrics = {
        "annualized_return": 0.12,
        "annualized_volatility": 0.16,
        "sharpe": 0.7,
        "max_drawdown": 0.12,
        "average_turnover": 0.25,
        "gross_total_return": 0.05,
        "net_total_return": 0.04,
    }
    result = backtest_analysis(metrics, monthly, pd.Series([0.01, -0.01, 0.01]))
    assert result["status"] == "历史表现相对稳健"
    assert math.isfinite(result["diagnostics"]["基准年化收益"])
