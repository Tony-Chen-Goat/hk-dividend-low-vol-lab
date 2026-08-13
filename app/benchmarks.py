from __future__ import annotations

import numpy as np
import pandas as pd


def add_benchmark_curves(
    monthly: pd.DataFrame,
    prices: pd.DataFrame,
    benchmarks: dict[str, str],
) -> tuple[pd.DataFrame, pd.Series | None]:
    """Align benchmark forward returns and cumulative curves to strategy months.

    Returns are calculated from consecutive actual month-end prices. Missing
    months stay missing instead of being converted into artificial zero returns.
    """
    result = monthly.copy()
    if result.empty or prices.empty:
        return result, None

    result["month_end"] = pd.to_datetime(result["month_end"])
    result["period"] = result["month_end"].dt.to_period("M")
    price_data = prices.copy()
    price_data["trade_date"] = pd.to_datetime(price_data["trade_date"])
    primary_return = None

    for benchmark_name, benchmark_symbol in benchmarks.items():
        bench = price_data[price_data["symbol"] == benchmark_symbol].sort_values("trade_date").copy()
        if bench.empty:
            continue
        bench["period"] = bench["trade_date"].dt.to_period("M")
        bench = bench.groupby("period", as_index=False).tail(1).sort_values("period")
        bench["benchmark_return"] = (
            pd.to_numeric(bench["adjusted_close"], errors="coerce").shift(-1)
            / pd.to_numeric(bench["adjusted_close"], errors="coerce")
            - 1
        )
        next_period = bench["period"].shift(-1)
        bench.loc[next_period != bench["period"] + 1, "benchmark_return"] = np.nan

        return_by_period = bench.set_index("period")["benchmark_return"]
        aligned_return = pd.to_numeric(result["period"].map(return_by_period), errors="coerce")
        result[f"{benchmark_name}_return"] = aligned_return
        result[f"{benchmark_name}_value"] = (1 + aligned_return).cumprod()
        if primary_return is None:
            primary_return = result[f"{benchmark_name}_return"]

    return result, primary_return
