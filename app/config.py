from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

APP_NAME = "港股红利低波实验室"
APP_SUBTITLE = "HK Dividend Low Volatility Lab"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "hk_dividend_lab.sqlite3"

# 2026-08-06 通过 Yahoo Finance 五日只读请求实际验证；仍可能因 Yahoo 变更而失效。
BENCHMARKS = {"恒生指数": "^HSI", "恒生中国企业指数": "^HSCE"}

FACTOR_WEIGHTS = OrderedDict(
    [
        ("dividend_yield_3y", 0.20),
        ("dividend_yield_ttm", 0.10),
        ("dividend_stability", 0.05),
        ("dividend_growth_3y", 0.05),
        ("volatility_60d", 0.15),
        ("volatility_120d", 0.10),
        ("downside_volatility_60d", 0.07),
        ("max_drawdown_120d", 0.05),
        ("daily_volatility_cv", 0.03),
        ("payout_sustainability", 0.07),
        ("cashflow_coverage", 0.05),
        ("avg_traded_value_20d", 0.05),
        ("free_float_market_cap", 0.03),
    ]
)

MODEL_YAHOO_10 = "yahoo_10"
MODEL_FULL_13 = "full_13"

YAHOO_FACTOR_WEIGHTS = OrderedDict(
    [
        ("dividend_yield_3y", 0.24),
        ("dividend_yield_ttm", 0.12),
        ("dividend_stability", 0.06),
        ("dividend_growth_3y", 0.05),
        ("volatility_60d", 0.18),
        ("volatility_120d", 0.12),
        ("downside_volatility_60d", 0.08),
        ("max_drawdown_120d", 0.06),
        ("daily_volatility_cv", 0.04),
        ("avg_traded_value_20d", 0.05),
    ]
)

MODEL_LABELS = OrderedDict(
    [
        (MODEL_YAHOO_10, "Yahoo 基础10因子"),
        (MODEL_FULL_13, "完整13因子"),
    ]
)

MODEL_FACTOR_WEIGHTS = {
    MODEL_YAHOO_10: YAHOO_FACTOR_WEIGHTS,
    MODEL_FULL_13: FACTOR_WEIGHTS,
}

FACTOR_GROUPS = {
    "红利": ["dividend_yield_3y", "dividend_yield_ttm", "dividend_stability", "dividend_growth_3y"],
    "低波": ["volatility_60d", "volatility_120d", "downside_volatility_60d", "max_drawdown_120d", "daily_volatility_cv"],
    "质量/流动性/规模": ["payout_sustainability", "cashflow_coverage", "avg_traded_value_20d", "free_float_market_cap"],
}

MODEL_FACTOR_GROUPS = {
    MODEL_YAHOO_10: {
        "红利": ["dividend_yield_3y", "dividend_yield_ttm", "dividend_stability", "dividend_growth_3y"],
        "低波": ["volatility_60d", "volatility_120d", "downside_volatility_60d", "max_drawdown_120d", "daily_volatility_cv"],
        "流动性": ["avg_traded_value_20d"],
    },
    MODEL_FULL_13: FACTOR_GROUPS,
}

FACTOR_LABELS = {
    "dividend_yield_3y": "三年平均股息率",
    "dividend_yield_ttm": "最近12个月股息率",
    "dividend_stability": "连续分红稳定性",
    "dividend_growth_3y": "三年股息增长率",
    "volatility_60d": "60日年化波动率",
    "volatility_120d": "120日年化波动率",
    "downside_volatility_60d": "60日下行波动率",
    "max_drawdown_120d": "120日最大回撤",
    "daily_volatility_cv": "日频波动稳定度代理因子",
    "payout_sustainability": "股息支付率可持续性",
    "cashflow_coverage": "现金流覆盖能力",
    "avg_traded_value_20d": "20日平均成交额",
    "free_float_market_cap": "流通市值",
}

LOWER_IS_BETTER = {
    "volatility_60d",
    "volatility_120d",
    "downside_volatility_60d",
    "max_drawdown_120d",
    "daily_volatility_cv",
}

RISK_DEFAULTS = {
    "min_listing_days": 252,
    "min_price_hkd": 1.0,
    "min_valid_trading_ratio_60d": 0.80,
    "max_suspension_days": 20,
    "max_dividend_cut": 0.30,
    "min_avg_traded_value_20d": 5_000_000.0,
    "min_free_float_market_cap": 500_000_000.0,
    "max_stock_weight": 0.05,
    "min_stock_weight": 0.01,
    "max_sector_weight": 0.25,
    "max_top5_weight": 0.25,
    "turnover_warning": 0.30,
    "max_turnover": 0.40,
}

UNIVERSE_COLUMNS = [
    "symbol",
    "name",
    "sector",
    "security_type",
    "board",
    "index_membership",
    "effective_date",
    "end_date",
    "source",
]
