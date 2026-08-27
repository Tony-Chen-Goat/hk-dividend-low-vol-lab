from __future__ import annotations

import numpy as np
import pandas as pd


ENTRY_COLUMNS = [
    "symbol", "signal_as_of", "latest_price", "ma5", "ma20", "return_20d",
    "trend_strength", "reference_ma", "reference_price", "reference_low",
    "reference_high", "price_vs_reference", "entry_guidance", "price_data_points",
]


def _guidance(deviation: float) -> str:
    if deviation > 0.03:
        return "高于参考线较多，等待回落，避免追高"
    if deviation > 0.01:
        return "略高于观察区间，耐心等待靠近参考线"
    if deviation >= -0.01:
        return "已进入参考观察区间，可结合公告分批观察"
    if deviation >= -0.05:
        return "低于参考线，等待止跌并重新站稳后再观察"
    return "明显跌破参考线，暂停机械买入并复核基本面与公告"


def calculate_entry_references(
    selected: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    limit: int = 10,
    band_pct: float = 0.01,
) -> pd.DataFrame:
    """Calculate descriptive MA5/MA20 entry references for ranked selections."""
    if (
        selected.empty
        or prices.empty
        or "symbol" not in selected
        or not {"symbol", "trade_date", "close"}.issubset(prices.columns)
    ):
        return pd.DataFrame(columns=ENTRY_COLUMNS)

    ranked = selected.copy()
    if "target_weight" in ranked:
        weights = pd.to_numeric(ranked["target_weight"], errors="coerce").fillna(0)
        ranked = ranked[weights > 0].copy()
    if "排名" in ranked:
        ranked = ranked.sort_values("排名", kind="stable")
    elif "model_score" in ranked:
        ranked = ranked.sort_values("model_score", ascending=False, kind="stable")
    ranked = ranked.head(max(1, int(limit)))

    clean_prices = prices.copy()
    clean_prices["trade_date"] = pd.to_datetime(clean_prices["trade_date"], errors="coerce")
    clean_prices["close"] = pd.to_numeric(clean_prices["close"], errors="coerce")
    clean_prices = clean_prices.dropna(subset=["trade_date", "close"])
    clean_prices = clean_prices[clean_prices["close"] > 0]

    rows: list[dict] = []
    for symbol in ranked["symbol"].astype(str):
        history = (
            clean_prices[clean_prices["symbol"].astype(str) == symbol]
            .sort_values("trade_date", kind="stable")
            .drop_duplicates("trade_date", keep="last")
        )
        closes = history["close"]
        row = {column: np.nan for column in ENTRY_COLUMNS}
        row["symbol"] = symbol
        row["price_data_points"] = int(len(closes))
        if history.empty:
            row["entry_guidance"] = "缺少价格数据，暂不提供均线参考"
            rows.append(row)
            continue

        row["signal_as_of"] = history["trade_date"].iloc[-1]
        row["latest_price"] = float(closes.iloc[-1])
        if len(closes) < 20:
            row["ma5"] = float(closes.tail(5).mean()) if len(closes) >= 5 else np.nan
            row["entry_guidance"] = f"仅有{len(closes)}个有效交易日，样本不足20日"
            rows.append(row)
            continue

        latest_price = float(closes.iloc[-1])
        ma5 = float(closes.tail(5).mean())
        ma20 = float(closes.tail(20).mean())
        return_20d = float(latest_price / closes.iloc[-21] - 1) if len(closes) >= 21 else np.nan
        strong = bool(ma5 >= ma20 and pd.notna(return_20d) and return_20d > 0)
        reference = ma5 if strong else ma20
        deviation = float(latest_price / reference - 1) if reference > 0 else np.nan
        row.update(
            {
                "ma5": ma5,
                "ma20": ma20,
                "return_20d": return_20d,
                "trend_strength": "短线趋势较强" if strong else "趋势一般或偏弱",
                "reference_ma": "5日均线" if strong else "20日均线",
                "reference_price": reference,
                "reference_low": reference * (1 - band_pct),
                "reference_high": reference * (1 + band_pct),
                "price_vs_reference": deviation,
                "entry_guidance": _guidance(deviation),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=ENTRY_COLUMNS)
