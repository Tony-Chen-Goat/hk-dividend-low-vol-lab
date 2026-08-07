from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .portfolio import portfolio_turnover


def month_end_prices(prices: pd.DataFrame, price_column: str = "adjusted_close") -> pd.DataFrame:
    data = prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    return data.sort_values("trade_date").groupby(["symbol", data["trade_date"].dt.to_period("M")]).tail(1)


def calculate_forward_returns(prices: pd.DataFrame, price_column: str = "adjusted_close") -> pd.DataFrame:
    monthly = month_end_prices(prices, price_column).sort_values(["symbol", "trade_date"]).copy()
    monthly["forward_return"] = monthly.groupby("symbol")[price_column].shift(-1) / monthly[price_column] - 1
    monthly["next_month_end"] = monthly.groupby("symbol")["trade_date"].shift(-1)
    return monthly.rename(columns={"trade_date": "month_end"})[["symbol", "month_end", "next_month_end", "forward_return"]]


def run_monthly_backtest(holdings: pd.DataFrame, transaction_cost: float = 0.001) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"month_end", "symbol", "target_weight", "forward_return"}
    if missing := required - set(holdings.columns):
        raise ValueError(f"回测持仓缺少列: {', '.join(sorted(missing))}")
    monthly_rows, detail_rows = [], []
    previous = pd.Series(dtype=float)
    for month, group in holdings.sort_values("month_end").groupby("month_end"):
        current = group.set_index("symbol")["target_weight"]
        turnover = portfolio_turnover(previous, current)
        gross = float((group["target_weight"] * group["forward_return"].fillna(0)).sum())
        cost = turnover * transaction_cost
        net = gross - cost
        monthly_rows.append({"month_end": pd.Timestamp(month), "gross_return": gross, "transaction_cost": cost, "net_return": net, "turnover": turnover, "cash_weight": max(0.0, 1 - current.sum())})
        detail = group.copy()
        detail["contribution"] = detail["target_weight"] * detail["forward_return"]
        detail_rows.append(detail)
        previous = current
    monthly = pd.DataFrame(monthly_rows)
    if not monthly.empty:
        monthly["net_value"] = (1 + monthly["net_return"]).cumprod()
        monthly["gross_value"] = (1 + monthly["gross_return"]).cumprod()
        monthly["drawdown"] = monthly["net_value"] / monthly["net_value"].cummax() - 1
    return monthly, pd.concat(detail_rows, ignore_index=True) if detail_rows else pd.DataFrame()


def performance_metrics(monthly: pd.DataFrame, benchmark_returns: pd.Series | None = None) -> dict[str, float]:
    returns = monthly.get("net_return", pd.Series(dtype=float)).dropna()
    if returns.empty:
        return {key: np.nan for key in ["annualized_return", "annualized_volatility", "sharpe", "information_ratio", "max_drawdown", "calmar", "average_turnover", "win_rate", "gross_total_return", "net_total_return"]}
    total = float((1 + returns).prod() - 1)
    annualized_return = float((1 + total) ** (12 / len(returns)) - 1)
    volatility = float(returns.std(ddof=1) * math.sqrt(12)) if len(returns) > 1 else np.nan
    sharpe = float(returns.mean() / returns.std(ddof=1) * math.sqrt(12)) if len(returns) > 1 and returns.std(ddof=1) else np.nan
    curve = (1 + returns).cumprod()
    max_dd = float(abs((curve / curve.cummax() - 1).min()))
    information = np.nan
    if benchmark_returns is not None:
        active = returns.align(benchmark_returns, join="inner")[0] - returns.align(benchmark_returns, join="inner")[1]
        information = float(active.mean() / active.std(ddof=1) * math.sqrt(12)) if len(active) > 1 and active.std(ddof=1) else np.nan
    gross = monthly.get("gross_return", returns)
    return {
        "annualized_return": annualized_return, "annualized_volatility": volatility, "sharpe": sharpe,
        "information_ratio": information, "max_drawdown": max_dd,
        "calmar": annualized_return / max_dd if max_dd else np.nan,
        "average_turnover": float(monthly["turnover"].mean()) if "turnover" in monthly else np.nan,
        "win_rate": float((returns > 0).mean()), "gross_total_return": float((1 + gross).prod() - 1),
        "net_total_return": total,
    }


def expanding_walk_forward_splits(months, train_years: int = 5, validation_months: int = 12):
    values = pd.DatetimeIndex(sorted(pd.to_datetime(pd.Series(months).dropna().unique())))
    min_train = train_years * 12
    if len(values) < min_train + validation_months:
        return []
    splits = []
    for start in range(min_train, len(values), validation_months):
        validation = values[start : start + validation_months]
        if len(validation) == 0:
            break
        splits.append((values[:start], validation))
    return splits
