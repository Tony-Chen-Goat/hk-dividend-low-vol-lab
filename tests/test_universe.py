import numpy as np
import pandas as pd

from app.universe import apply_hk_risk_filters


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
