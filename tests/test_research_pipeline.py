import numpy as np
import pandas as pd

from app.config import MODEL_YAHOO_10, YAHOO_FACTOR_WEIGHTS
from app.database import connect, initialize_database, read_table, upsert_rows
from app.experiment_store import get_experiment
from app.research_pipeline import compute_and_store_features, load_feature_panel


def test_feature_experiment_filters_each_month_and_freezes_version(tmp_path):
    path = tmp_path / "pipeline.sqlite3"
    dates = pd.bdate_range("2019-01-01", "2024-03-29")
    price_rows = []
    for symbol, start_price, volume in [
        ("0005.HK", 50.0, 2_000_000.0),
        ("0006.HK", 0.5, 2_000_000.0),
    ]:
        values = start_price * np.cumprod(1 + np.tile([0.001, -0.0005], len(dates) // 2 + 1)[:len(dates)])
        for date, value in zip(dates, values):
            price_rows.append({
                "symbol": symbol, "trade_date": date.date().isoformat(),
                "close": float(value), "adjusted_close": float(value),
                "volume": volume, "source": "test",
            })
    dividend_rows = []
    for symbol in ["0005.HK", "0006.HK"]:
        for year in range(2019, 2024):
            dividend_rows.append({
                "symbol": symbol, "ex_date": f"{year}-06-01",
                "dividend_per_share": 1.0, "source": "test",
            })
    securities = [
        {
            "symbol": "0005.HK", "name": "A", "sector": "金融",
            "security_type": "Common Stock", "board": "Main Board",
            "source": "test",
        },
        {
            "symbol": "0006.HK", "name": "B", "sector": "公用事业",
            "security_type": "Common Stock", "board": "Main Board",
            "source": "test",
        },
    ]
    initialize_database(path)
    with connect(path) as conn:
        upsert_rows(conn, "security_master", securities)
        upsert_rows(conn, "daily_prices", price_rows)
        upsert_rows(conn, "dividends", dividend_rows)

    panel_one = compute_and_store_features(
        path,
        dict(YAHOO_FACTOR_WEIGHTS),
        model_name=MODEL_YAHOO_10,
        experiment_name="版本一",
        risk_settings={"min_price_hkd": 1.0},
    )
    panel_two = compute_and_store_features(
        path,
        dict(YAHOO_FACTOR_WEIGHTS),
        model_name=MODEL_YAHOO_10,
        experiment_name="版本二",
        risk_settings={"min_price_hkd": 1.0},
    )
    experiment_one = panel_one["experiment_id"].iloc[0]
    experiment_two = panel_two["experiment_id"].iloc[0]

    assert experiment_one != experiment_two
    features = read_table("monthly_features", path)
    assert set(features["experiment_id"]) == {experiment_one, experiment_two}
    assert set(features["symbol"]) == {"0005.HK"}
    universe = read_table("experiment_universe", path)
    excluded = universe[(universe["experiment_id"] == experiment_one) & (universe["symbol"] == "0006.HK")]
    assert not excluded.empty
    assert excluded["included"].eq(0).all()
    assert excluded["exclusion_reasons"].str.contains("股价低于").all()
    loaded = load_feature_panel(path, MODEL_YAHOO_10, experiment_one)
    assert set(loaded["symbol"]) == {"0005.HK"}
    assert "forward_return" in loaded
    assert get_experiment(experiment_one, path)["status"] == "features_ready"
