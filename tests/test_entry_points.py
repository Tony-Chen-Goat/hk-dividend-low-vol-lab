import pandas as pd

from app.entry_points import calculate_entry_references


def _prices(symbol: str, values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": pd.date_range("2026-01-01", periods=len(values), freq="B"),
            "close": values,
        }
    )


def test_strong_trend_uses_five_day_average_as_reference():
    selected = pd.DataFrame({"symbol": ["0001.HK"], "target_weight": [0.1], "model_score": [80.0]})
    result = calculate_entry_references(selected, _prices("0001.HK", list(range(10, 31))))

    row = result.iloc[0]
    assert row["trend_strength"] == "短线趋势较强"
    assert row["reference_ma"] == "5日均线"
    assert row["reference_price"] == row["ma5"]
    assert row["reference_low"] < row["reference_price"] < row["reference_high"]


def test_weak_trend_uses_twenty_day_average_and_warns_on_breakdown():
    selected = pd.DataFrame({"symbol": ["0002.HK"], "target_weight": [0.1], "model_score": [70.0]})
    result = calculate_entry_references(selected, _prices("0002.HK", list(range(31, 10, -1))))

    row = result.iloc[0]
    assert row["trend_strength"] == "趋势一般或偏弱"
    assert row["reference_ma"] == "20日均线"
    assert row["reference_price"] == row["ma20"]
    assert "暂停机械买入" in row["entry_guidance"]


def test_entry_reference_limits_to_invested_top_ten_and_handles_short_history():
    selected = pd.DataFrame(
        {
            "symbol": [f"{number:04d}.HK" for number in range(1, 13)],
            "target_weight": [0.05] * 11 + [0.0],
            "model_score": list(range(12, 0, -1)),
        }
    )
    prices = pd.concat([_prices(symbol, [10, 11, 12]) for symbol in selected["symbol"]], ignore_index=True)
    result = calculate_entry_references(selected, prices, limit=10)

    assert len(result) == 10
    assert result["symbol"].tolist() == selected["symbol"].head(10).tolist()
    assert result["entry_guidance"].str.contains("样本不足20日").all()
