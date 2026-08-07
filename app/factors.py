from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd


TRADING_DAYS = 252


def adjusted_returns(adjusted_close: pd.Series) -> pd.Series:
    return pd.to_numeric(adjusted_close, errors="coerce").pct_change(fill_method=None)


def ttm_dividend_yield(dividends: pd.DataFrame, month_end, unadjusted_close: float) -> float:
    if not unadjusted_close or pd.isna(unadjusted_close) or unadjusted_close <= 0:
        return np.nan
    end = pd.Timestamp(month_end)
    start = end - pd.DateOffset(months=12)
    ex_dates = pd.to_datetime(dividends.get("ex_date"), errors="coerce")
    values = pd.to_numeric(dividends.get("dividend_per_share"), errors="coerce")
    total = values[(ex_dates > start) & (ex_dates <= end)].sum(min_count=1)
    return float(total / unadjusted_close) if pd.notna(total) else np.nan


def annual_dividends(dividends: pd.DataFrame, as_of=None) -> pd.Series:
    data = dividends.copy()
    data["ex_date"] = pd.to_datetime(data["ex_date"], errors="coerce")
    if as_of is not None:
        data = data[data["ex_date"] <= pd.Timestamp(as_of)]
    return data.groupby(data["ex_date"].dt.year)["dividend_per_share"].sum(min_count=1)


def three_year_average_yield(dividends: pd.DataFrame, year_end_closes: dict[int, float], month_end) -> float:
    year = pd.Timestamp(month_end).year
    complete_years = [year - 3, year - 2, year - 1]
    annual = annual_dividends(dividends, month_end)
    yields = []
    for target_year in complete_years:
        close = year_end_closes.get(target_year)
        value = annual.get(target_year, np.nan)
        if pd.isna(value) or close is None or pd.isna(close) or close <= 0:
            return np.nan
        yields.append(value / close)
    return float(np.mean(yields))


def dividend_growth_3y(dividends: pd.DataFrame, month_end) -> float:
    year = pd.Timestamp(month_end).year
    annual = annual_dividends(dividends, month_end)
    start, finish = annual.get(year - 3, np.nan), annual.get(year - 1, np.nan)
    if pd.isna(start) or pd.isna(finish) or start <= 0:
        return np.nan
    return float((finish / start) ** (1 / 2) - 1)


def dividend_stability_components(dividends: pd.DataFrame, month_end) -> dict[str, float]:
    year = pd.Timestamp(month_end).year
    annual = annual_dividends(dividends, month_end).reindex(range(year - 5, year), fill_value=0.0)
    consecutive = 0
    for value in annual.iloc[::-1]:
        if value > 0:
            consecutive += 1
        else:
            break
    positive = annual[annual > 0]
    cv = float(positive.std(ddof=0) / positive.mean()) if len(positive) >= 2 and positive.mean() > 0 else np.nan
    prior, latest = annual.iloc[-2], annual.iloc[-1]
    cut = float((prior - latest) / prior) if prior > 0 else np.nan
    return {"consecutive_years": consecutive, "dividend_cv": cv, "large_cut": float(pd.notna(cut) and cut > 0.30)}


def annualized_volatility(adjusted_close: pd.Series, window: int) -> float:
    returns = adjusted_returns(adjusted_close).dropna().tail(window)
    return float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS)) if len(returns) >= window else np.nan


def downside_volatility(adjusted_close: pd.Series, window: int = 60) -> float:
    returns = adjusted_returns(adjusted_close).dropna().tail(window)
    if len(returns) < window:
        return np.nan
    negative = returns[returns < 0]
    return float(negative.std(ddof=1) * math.sqrt(TRADING_DAYS)) if len(negative) >= 2 else 0.0


def max_drawdown(adjusted_close: pd.Series, window: int = 120) -> float:
    values = pd.to_numeric(adjusted_close, errors="coerce").dropna().tail(window)
    if len(values) < window:
        return np.nan
    drawdown = values / values.cummax() - 1
    return float(abs(drawdown.min()))


def daily_volatility_cv(adjusted_close: pd.Series) -> float:
    returns = adjusted_returns(adjusted_close)
    rolling = returns.rolling(20, min_periods=20).std(ddof=1) * math.sqrt(TRADING_DAYS)
    values = rolling.dropna().tail(20)
    if len(values) < 20 or values.mean() == 0:
        return np.nan
    return float(values.std(ddof=1) / values.mean())


def payout_sustainability_score(payout_ratio: float, net_income: float | None = None) -> float:
    if pd.isna(payout_ratio) or payout_ratio <= 0 or (net_income is not None and pd.notna(net_income) and net_income < 0):
        return 0.0
    if payout_ratio < 0.20:
        return float(payout_ratio / 0.20 * 40)
    if payout_ratio <= 0.70:
        return 100.0
    if payout_ratio <= 0.90:
        return float(100 - (payout_ratio - 0.70) / 0.20 * 70)
    return 0.0


def cashflow_coverage(operating_cash_flow: float, cash_dividends_paid: float) -> float:
    if pd.isna(operating_cash_flow) or pd.isna(cash_dividends_paid) or cash_dividends_paid == 0:
        return np.nan
    return float(operating_cash_flow / abs(cash_dividends_paid))


def _year_end_closes(prices: pd.DataFrame, month_end) -> dict[int, float]:
    data = prices[pd.to_datetime(prices["trade_date"]) <= pd.Timestamp(month_end)].copy()
    data["year"] = pd.to_datetime(data["trade_date"]).dt.year
    return data.sort_values("trade_date").groupby("year").tail(1).set_index("year")["close"].to_dict()


def calculate_symbol_factors(
    prices: pd.DataFrame, dividends: pd.DataFrame, fundamentals: pd.DataFrame | None, month_end,
) -> dict[str, float]:
    end = pd.Timestamp(month_end)
    px = prices[pd.to_datetime(prices["trade_date"]) <= end].sort_values("trade_date")
    if px.empty:
        return {}
    close = float(px.iloc[-1]["close"])
    div = dividends[pd.to_datetime(dividends.get("ex_date"), errors="coerce") <= end] if not dividends.empty else dividends
    latest = None
    if fundamentals is not None and not fundamentals.empty:
        eligible = fundamentals[(pd.to_datetime(fundamentals["published_date"], errors="coerce") <= end)]
        if not eligible.empty:
            latest = eligible.sort_values("published_date").iloc[-1]
    result = {
        "dividend_yield_3y": three_year_average_yield(div, _year_end_closes(px, end), end),
        "dividend_yield_ttm": ttm_dividend_yield(div, end, close),
        "dividend_growth_3y": dividend_growth_3y(div, end),
        "volatility_60d": annualized_volatility(px["adjusted_close"], 60),
        "volatility_120d": annualized_volatility(px["adjusted_close"], 120),
        "downside_volatility_60d": downside_volatility(px["adjusted_close"], 60),
        "max_drawdown_120d": max_drawdown(px["adjusted_close"], 120),
        "daily_volatility_cv": daily_volatility_cv(px["adjusted_close"]),
        "avg_traded_value_20d": float((px.tail(20)["close"] * px.tail(20)["volume"]).mean()) if len(px) >= 20 else np.nan,
    }
    stability = dividend_stability_components(div, end)
    result.update({
        "consecutive_dividend_years": stability["consecutive_years"],
        "dividend_cv": stability["dividend_cv"],
        "no_large_dividend_cut": 1 - stability["large_cut"],
    })
    if latest is not None:
        result["payout_sustainability"] = payout_sustainability_score(latest.get("payout_ratio"), latest.get("net_income"))
        result["cashflow_coverage"] = cashflow_coverage(latest.get("operating_cash_flow"), latest.get("cash_dividends_paid"))
        shares = latest.get("free_float_shares")
        result["free_float_market_cap"] = close * shares if pd.notna(shares) else np.nan
    else:
        result.update({"payout_sustainability": np.nan, "cashflow_coverage": np.nan, "free_float_market_cap": np.nan})
    return result


def calculate_monthly_features(prices: pd.DataFrame, dividends: pd.DataFrame, fundamentals: pd.DataFrame, month_end) -> pd.DataFrame:
    rows = []
    for symbol, px in prices.groupby("symbol"):
        div = dividends[dividends["symbol"] == symbol] if not dividends.empty else pd.DataFrame(columns=["ex_date", "dividend_per_share"])
        fund = fundamentals[fundamentals["symbol"] == symbol] if not fundamentals.empty else pd.DataFrame()
        row = calculate_symbol_factors(px, div, fund, month_end)
        if row:
            row.update({"symbol": symbol, "month_end": pd.Timestamp(month_end)})
            rows.append(row)
    return pd.DataFrame(rows)
