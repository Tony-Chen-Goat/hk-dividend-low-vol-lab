from datetime import date
from types import SimpleNamespace

import pandas as pd

from app.yahoo_provider import fetch_yahoo_data


class _TickerWithEmptyInfo:
    actions = pd.DataFrame()

    def get_info(self):
        return None


def test_empty_yahoo_company_info_does_not_fail_price_update(monkeypatch):
    index = pd.DatetimeIndex(["2026-08-03"], name="Date")
    downloaded = pd.DataFrame(
        {
            "Open": [10.0],
            "High": [10.5],
            "Low": [9.8],
            "Close": [10.2],
            "Adj Close": [10.2],
            "Volume": [1_000_000],
        },
        index=index,
    )
    fake_yfinance = SimpleNamespace(
        download=lambda *args, **kwargs: downloaded,
        Ticker=lambda symbol: _TickerWithEmptyInfo(),
    )
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yfinance)

    result = fetch_yahoo_data(
        ["0267.HK"],
        date(2026, 8, 1),
        date(2026, 8, 5),
        attempts=1,
    )

    assert len(result.prices) == 1
    assert result.failures == []
    assert result.securities.iloc[0]["symbol"] == "0267.HK"
    assert pd.isna(result.securities.iloc[0]["name"])
