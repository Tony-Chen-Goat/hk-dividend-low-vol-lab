import pandas as pd
import pytest

from app.yahoo_provider import normalize_hk_symbol, transform_price_frame


@pytest.mark.parametrize("raw,expected", [(700, "0700.HK"), ("0700", "0700.HK"), ("700.HK", "0700.HK"), (9988, "9988.HK"), ("09988.HK", "9988.HK")])
def test_normalize_hk_symbol(raw, expected):
    assert normalize_hk_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["AAPL", "", "00000.HK", "123456.HK"])
def test_invalid_hk_symbol(raw):
    with pytest.raises(ValueError):
        normalize_hk_symbol(raw)


def test_transform_yahoo_price_frame():
    frame = pd.DataFrame({
        "Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.5],
        "Adj Close": [10.2], "Volume": [1000],
    }, index=pd.DatetimeIndex(["2024-01-02"], name="Date"))
    result = transform_price_frame(frame, "0700.HK")
    assert result.iloc[0]["adjusted_close"] == 10.2
    assert result.iloc[0]["traded_value"] == 10_500
    assert result.iloc[0]["source"].startswith("Yahoo")
