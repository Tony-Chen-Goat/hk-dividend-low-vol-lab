import math

import pandas as pd

from app.benchmarks import add_benchmark_curves
from app.monthly_chart import equity_curve_chart, selected_month_from_chart_event
from app.monthly_details import monthly_rebalance_details


def test_benchmark_curves_use_actual_levels_and_keep_missing_months_empty():
    monthly = pd.DataFrame({
        "month_end": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]),
        "net_return": [0.01, 0.02, 0.03],
    })
    prices = pd.DataFrame({
        "symbol": ["^HSI", "^HSI", "^HSI"],
        "trade_date": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-04-30"]),
        "adjusted_close": [100.0, 110.0, 121.0],
    })

    result, benchmark_return = add_benchmark_curves(monthly, prices, {"恒生指数": "^HSI"})

    assert math.isclose(result.loc[0, "恒生指数_value"], 1.1)
    assert pd.isna(result.loc[1, "恒生指数_value"])
    assert pd.isna(result.loc[2, "恒生指数_value"])
    assert pd.isna(benchmark_return.iloc[1])


def test_equity_curve_chart_has_chinese_labels_year_ticks_and_month_ticks():
    monthly = pd.DataFrame({
        "month_end": pd.to_datetime(["2024-01-31", "2024-02-29"]),
        "net_value": [1.0, 1.1],
        "gross_value": [1.0, 1.11],
        "恒生指数_value": [1.0, 0.98],
        "恒生中国企业指数_value": [1.0, 0.97],
    })

    figure = equity_curve_chart(monthly)

    assert [trace.name for trace in figure.data] == [
        "扣费后组合净值", "扣费前组合净值", "恒生指数", "恒生国企指数"
    ]
    assert figure.data[0].mode == "lines+markers"
    assert all(trace.connectgaps is False for trace in figure.data)
    assert figure.layout.xaxis.dtick == "M12"
    assert figure.layout.xaxis.minor.dtick == "M1"


def test_selected_month_and_monthly_dialog_details():
    event = {"selection": {"points": [{"x": "2024-02-29"}]}}
    selected_month = selected_month_from_chart_event(event)
    monthly = pd.DataFrame({
        "month_end": pd.to_datetime(["2024-02-29"]),
        "entered_count": [1],
        "exited_count": [1],
        "entered_symbols": ["0005.HK"],
        "exited_symbols": ["0001.HK"],
        "retained_symbols": ["0002.HK"],
    })
    holdings = pd.DataFrame({
        "month_end": pd.to_datetime(["2024-02-29", "2024-02-29"]),
        "symbol": ["0005.HK", "0002.HK"],
        "target_weight": [0.0, 0.1],
    })

    summary, transactions, positions = monthly_rebalance_details(monthly, holdings, selected_month)

    assert selected_month == pd.Timestamp("2024-02-29")
    assert summary["entered_symbols"] == "0005.HK"
    assert transactions["动作"].tolist() == ["本月新增", "本月退出", "继续持有"]
    assert positions["symbol"].tolist() == ["0002.HK"]
