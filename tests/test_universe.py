import numpy as np
import pandas as pd

from app.universe import apply_hk_risk_filters, universe_fingerprint


def test_yahoo_mode_does_not_require_free_float_market_cap():
    snapshot = pd.DataFrame(
        [
            {
                "symbol": "0700.HK",
                "security_type": "Common Stock",
                "board": "Main Board",
                "listing_days": 500,
                "close": 500.0,
                "valid_trading_ratio_60d": 1.0,
                "max_suspension_days": 0,
                "avg_traded_value_20d": 1_000_000_000.0,
                "free_float_market_cap": np.nan,
            }
        ]
    )

    yahoo = apply_hk_risk_filters(
        snapshot,
        {"require_free_float_market_cap": False},
    )
    full = apply_hk_risk_filters(
        snapshot,
        {"require_free_float_market_cap": True},
    )

    assert len(yahoo.included) == 1
    assert len(full.excluded) == 1
    assert "自由流通市值" in full.excluded.iloc[0]["exclusion_reasons"]


def test_reit_is_allowed_by_default_but_can_be_disabled():
    snapshot = pd.DataFrame(
        [{
            "symbol": "0823.HK",
            "security_type": "REIT",
            "board": "Main Board",
            "listing_days": 500,
            "close": 35.0,
            "valid_trading_ratio_60d": 1.0,
            "max_suspension_days": 0,
            "avg_traded_value_20d": 100_000_000.0,
            "free_float_market_cap": np.nan,
        }]
    )
    allowed = apply_hk_risk_filters(
        snapshot,
        {"require_free_float_market_cap": False},
    )
    disabled = apply_hk_risk_filters(
        snapshot,
        {"require_free_float_market_cap": False, "allow_reit": False},
    )
    assert len(allowed.included) == 1
    assert "不支持的证券类型: REIT" in disabled.excluded.iloc[0]["exclusion_reasons"]


def test_reit_type_matching_is_case_insensitive():
    snapshot = pd.DataFrame(
        [{
            "symbol": "0823.HK",
            "security_type": "reit",
            "board": "Main Board",
            "listing_days": 500,
            "close": 35.0,
            "valid_trading_ratio_60d": 1.0,
            "max_suspension_days": 0,
            "avg_traded_value_20d": 100_000_000.0,
            "free_float_market_cap": np.nan,
        }]
    )
    result = apply_hk_risk_filters(
        snapshot,
        {"require_free_float_market_cap": False},
    )
    assert len(result.included) == 1


def test_universe_version_is_independent_of_csv_row_order():
    rows = [
        {
            "symbol": "0001.HK", "name": "A", "sector": "Utilities",
            "security_type": "Common Stock", "board": "Main Board",
            "index_membership": "HSI", "effective_date": "2026-01-01",
            "end_date": None, "source": "test",
        },
        {
            "symbol": "0823.HK", "name": "Link REIT", "sector": "Properties",
            "security_type": "REIT", "board": "Main Board",
            "index_membership": "HSI", "effective_date": "2026-01-01",
            "end_date": None, "source": "test",
        },
    ]
    forward = pd.DataFrame(rows)
    reversed_rows = pd.DataFrame(list(reversed(rows)))

    assert universe_fingerprint(forward) == universe_fingerprint(reversed_rows)


def test_repeated_filter_is_deterministic_and_nan_flags_are_not_true():
    snapshot = pd.DataFrame([
        {
            "symbol": "0002.HK", "security_type": "Common Stock",
            "board": "Main Board", "listing_days": 500, "close": 60.0,
            "valid_trading_ratio_60d": 1.0, "max_suspension_days": 0,
            "avg_traded_value_20d": 100_000_000.0,
            "stopped_dividend_1y": np.nan, "inactive_event_effective": np.nan,
        },
        {
            "symbol": "0001.HK", "security_type": "Common Stock",
            "board": "Main Board", "listing_days": 500, "close": 40.0,
            "valid_trading_ratio_60d": 1.0, "max_suspension_days": 0,
            "avg_traded_value_20d": 100_000_000.0,
            "stopped_dividend_1y": np.nan, "inactive_event_effective": np.nan,
        },
    ])
    settings = {"require_free_float_market_cap": False}

    first = apply_hk_risk_filters(snapshot, settings)
    second = apply_hk_risk_filters(snapshot.sample(frac=1, random_state=7), settings)

    assert first.excluded.empty
    assert second.excluded.empty
    assert first.included["symbol"].tolist() == ["0001.HK", "0002.HK"]
    assert second.included["symbol"].tolist() == ["0001.HK", "0002.HK"]
