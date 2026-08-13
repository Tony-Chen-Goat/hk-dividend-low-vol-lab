from __future__ import annotations

import pandas as pd


def monthly_rebalance_details(
    monthly: pd.DataFrame,
    holdings: pd.DataFrame,
    selected_month,
) -> tuple[pd.Series | None, pd.DataFrame, pd.DataFrame]:
    """Return the monthly summary, transaction list and invested holdings."""
    selected_period = pd.Timestamp(selected_month).to_period("M")

    monthly_data = monthly.copy()
    monthly_data["month_end"] = pd.to_datetime(monthly_data["month_end"])
    matching_months = monthly_data[monthly_data["month_end"].dt.to_period("M") == selected_period]
    if matching_months.empty:
        return None, pd.DataFrame(), pd.DataFrame()

    summary = matching_months.iloc[0]
    transactions = pd.DataFrame([
        {
            "动作": "本月新增",
            "数量": int(summary.get("entered_count", 0) or 0),
            "证券代码": summary.get("entered_symbols", "") or "—",
        },
        {
            "动作": "本月退出",
            "数量": int(summary.get("exited_count", 0) or 0),
            "证券代码": summary.get("exited_symbols", "") or "—",
        },
        {
            "动作": "继续持有",
            "数量": len([symbol for symbol in str(summary.get("retained_symbols", "") or "").split("、") if symbol]),
            "证券代码": summary.get("retained_symbols", "") or "—",
        },
    ])

    if holdings.empty or "month_end" not in holdings:
        return summary, transactions, pd.DataFrame()
    position_data = holdings.copy()
    position_data["month_end"] = pd.to_datetime(position_data["month_end"])
    positions = position_data[position_data["month_end"].dt.to_period("M") == selected_period].copy()
    if "target_weight" in positions:
        positions["target_weight"] = pd.to_numeric(positions["target_weight"], errors="coerce")
        positions = positions[positions["target_weight"] > 0].sort_values("target_weight", ascending=False)
    return summary, transactions, positions.reset_index(drop=True)
