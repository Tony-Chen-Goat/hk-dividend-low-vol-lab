from pathlib import Path

import pandas as pd

from app import stability
from app.database import connect, initialize_database, upsert_rows


def test_streamlit_runtime_is_exactly_pinned():
    requirements = (Path(__file__).parents[1] / "requirements.txt").read_text(encoding="utf-8").splitlines()
    streamlit_requirements = [line.strip() for line in requirements if line.strip().startswith("streamlit")]
    assert streamlit_requirements == ["streamlit==1.60.0"]
    assert "starlette<1.4.0" in requirements


def test_rolling_deploy_fingerprint_fallback(monkeypatch):
    monkeypatch.delattr(stability.universe_module, "universe_fingerprint")
    rows = pd.DataFrame([
        {
            "symbol": "0823.HK", "name": "Link REIT", "sector": "Properties",
            "security_type": "REIT", "board": "Main Board",
            "index_membership": "HSI", "effective_date": "2026-01-01",
            "end_date": None, "source": "test",
        },
        {
            "symbol": "0001.HK", "name": "A", "sector": "Utilities",
            "security_type": "Common Stock", "board": "Main Board",
            "index_membership": "HSI", "effective_date": "2026-01-01",
            "end_date": None, "source": "test",
        },
    ])

    assert stability.universe_fingerprint(rows) == stability.universe_fingerprint(rows.iloc[::-1])


def test_rolling_deploy_cutoff_fallback(monkeypatch, tmp_path):
    path = tmp_path / "rolling.sqlite3"
    initialize_database(path)
    with connect(path) as conn:
        upsert_rows(conn, "daily_prices", [
            {"symbol": symbol, "trade_date": day, "close": 10.0, "source": "test"}
            for symbol, day in [
                ("0001.HK", "2026-08-15"),
                ("0002.HK", "2026-08-15"),
                ("0003.HK", "2026-08-14"),
            ]
        ])
    monkeypatch.delattr(stability.database_module, "resolve_stock_data_cutoff")

    result = stability.resolve_stock_data_cutoff(
        path, ["0001.HK", "0002.HK", "0003.HK"],
    )

    assert result["as_of"] == "2026-08-15"
    assert result["aligned_symbols"] == 2


def test_rolling_deploy_recent_price_reader_fallback(monkeypatch):
    legacy_frame = pd.DataFrame([
        {"symbol": "0001.HK", "trade_date": "2026-08-14", "close": 10.0},
        {"symbol": "0001.HK", "trade_date": "2026-08-15", "close": 11.0},
        {"symbol": "9999.HK", "trade_date": "2026-08-14", "close": 20.0},
    ])

    def legacy_reader(path, lookback):
        return legacy_frame.copy()

    monkeypatch.setattr(stability.database_module, "read_recent_stock_prices", legacy_reader)
    result = stability.read_recent_stock_prices(
        "unused.sqlite3", 60, symbols=["0001.HK"], as_of="2026-08-14",
    )

    assert result[["symbol", "trade_date"]].to_dict("records") == [
        {"symbol": "0001.HK", "trade_date": "2026-08-14"},
    ]
