from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .config import FACTOR_LABELS, MODEL_LABELS


METRIC_DEFINITIONS = [
    ("annualized_return", "年化收益", "percent", "high"),
    ("annualized_volatility", "年化波动", "percent", "low"),
    ("sharpe", "夏普比率", "decimal", "high"),
    ("max_drawdown", "最大回撤", "percent", "low"),
    ("calmar", "Calmar比率", "decimal", "high"),
    ("average_turnover", "月均换手率", "percent", "low"),
    ("rank_icir", "Rank ICIR", "decimal", "high"),
    ("positive_ratio", "IC正值比例", "percent", "high"),
    ("information_ratio", "信息比率", "decimal", "high"),
    ("coverage", "数据覆盖率", "percent", "high"),
    ("cost_drag", "交易成本累计拖累", "percent", "low"),
]


def _number(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return np.nan
    return result if math.isfinite(result) else np.nan


def _record_value(record: dict, key: str) -> float:
    metrics = record.get("metrics") or {}
    if key == "coverage":
        return _number(record.get("coverage"))
    if key == "cost_drag":
        gross = _number(metrics.get("gross_total_return"))
        net = _number(metrics.get("net_total_return"))
        return gross - net if pd.notna(gross) and pd.notna(net) else np.nan
    return _number(metrics.get(key, record.get(key)))


def _format_value(value: float, style: str, *, signed: bool = False) -> str:
    if pd.isna(value):
        return "—"
    if style == "percent":
        return f"{value:+.1%}" if signed else f"{value:.1%}"
    return f"{value:+.2f}" if signed else f"{value:.2f}"


def _winner(a: float, b: float, direction: str) -> str:
    if pd.isna(a) or pd.isna(b):
        return "数据不足"
    tolerance = max(abs(a), abs(b), 1.0) * 1e-6
    if abs(a - b) <= tolerance:
        return "大致相同"
    if direction == "high":
        return "实验A" if a > b else "实验B"
    return "实验A" if a < b else "实验B"


def core_metric_comparison(record_a: dict, record_b: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    display_rows, raw_rows = [], []
    for key, label, style, direction in METRIC_DEFINITIONS:
        value_a = _record_value(record_a, key)
        value_b = _record_value(record_b, key)
        delta = value_b - value_a if pd.notna(value_a) and pd.notna(value_b) else np.nan
        winner = _winner(value_a, value_b, direction)
        display_rows.append({
            "指标": label,
            "实验A": _format_value(value_a, style),
            "实验B": _format_value(value_b, style),
            "差异（B-A）": _format_value(delta, style, signed=True),
            "相对占优": winner,
            "判断原则": "越高越好" if direction == "high" else "越低越稳/越省",
        })
        raw_rows.append({
            "category": "核心指标", "key": key, "label": label,
            "experiment_a": value_a, "experiment_b": value_b,
            "difference_b_minus_a": delta, "preferred": winner,
        })
    return pd.DataFrame(display_rows), pd.DataFrame(raw_rows)


def configuration_comparison(record_a: dict, record_b: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    backtest_a, backtest_b = record_a.get("backtest_settings") or {}, record_b.get("backtest_settings") or {}
    rows = [
        ("因子模式", MODEL_LABELS.get(record_a.get("model_name"), record_a.get("model_name")), MODEL_LABELS.get(record_b.get("model_name"), record_b.get("model_name"))),
        ("每月入选数量", backtest_a.get("selected_count", record_a.get("selected_count")), backtest_b.get("selected_count", record_b.get("selected_count"))),
        ("回测开始日期", backtest_a.get("backtest_start"), backtest_b.get("backtest_start")),
        ("股息率资金配置", f"{backtest_a.get('dividend_pct', 50)}%", f"{backtest_b.get('dividend_pct', 50)}%"),
        ("逆波动率资金配置", f"{backtest_a.get('inverse_volatility_pct', 50)}%", f"{backtest_b.get('inverse_volatility_pct', 50)}%"),
        ("单股上限", f"{_number(backtest_a.get('max_stock_weight', record_a.get('max_stock_weight'))):.1%}", f"{_number(backtest_b.get('max_stock_weight', record_b.get('max_stock_weight'))):.1%}"),
        ("单边交易成本", f"{_number(backtest_a.get('transaction_cost', record_a.get('transaction_cost'))):.3%}", f"{_number(backtest_b.get('transaction_cost', record_b.get('transaction_cost'))):.3%}"),
    ]
    display = pd.DataFrame(rows, columns=["配置", "实验A", "实验B"])
    display["是否相同"] = np.where(display["实验A"].astype(str) == display["实验B"].astype(str), "相同", "不同")
    raw = display.rename(columns={"配置": "label", "实验A": "experiment_a", "实验B": "experiment_b", "是否相同": "preferred"}).copy()
    raw.insert(0, "category", "组合配置")
    return display, raw


def factor_weight_comparison(record_a: dict, record_b: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    weights_a = record_a.get("factor_weights") or {}
    weights_b = record_b.get("factor_weights") or {}
    factors = list(dict.fromkeys([*weights_a, *weights_b]))
    rows = []
    for factor in factors:
        value_a, value_b = _number(weights_a.get(factor, 0)), _number(weights_b.get(factor, 0))
        rows.append({
            "因子": FACTOR_LABELS.get(factor, factor),
            "实验A": value_a,
            "实验B": value_b,
            "差异（B-A）": value_b - value_a,
        })
    display = pd.DataFrame(rows)
    raw = display.rename(columns={"因子": "label", "实验A": "experiment_a", "实验B": "experiment_b", "差异（B-A）": "difference_b_minus_a"}).copy()
    raw.insert(0, "category", "因子权重")
    return display, raw


def common_period_curves(backtests: pd.DataFrame, experiment_a: str, experiment_b: str) -> pd.DataFrame:
    if backtests.empty:
        return pd.DataFrame()
    data = backtests[backtests["experiment_id"].astype(str).isin([str(experiment_a), str(experiment_b)])].copy()
    if data.empty:
        return data
    data["month_end"] = pd.to_datetime(data["month_end"])
    pivot = data.pivot_table(index="month_end", columns="experiment_id", values="net_return", aggfunc="last")
    if str(experiment_a) not in pivot or str(experiment_b) not in pivot:
        return pd.DataFrame()
    common = pivot[[str(experiment_a), str(experiment_b)]].dropna().sort_index()
    if common.empty:
        return pd.DataFrame()
    result = pd.DataFrame({"month_end": common.index})
    for label, experiment_id in [("实验A", str(experiment_a)), ("实验B", str(experiment_b))]:
        result[f"{label}收益"] = pd.to_numeric(common[experiment_id], errors="coerce").to_numpy()
        result[f"{label}净值"] = (1 + result[f"{label}收益"]).cumprod()
        result[f"{label}回撤"] = result[f"{label}净值"] / result[f"{label}净值"].cummax() - 1
    return result


def common_period_figures(curves: pd.DataFrame) -> tuple[go.Figure, go.Figure]:
    colors = {"实验A": "#164E3B", "实验B": "#C76D2E"}
    net_figure, drawdown_figure = go.Figure(), go.Figure()
    for label in ["实验A", "实验B"]:
        net_figure.add_scatter(x=curves["month_end"], y=curves[f"{label}净值"], name=label, line={"color": colors[label], "width": 3})
        drawdown_figure.add_scatter(x=curves["month_end"], y=curves[f"{label}回撤"], name=label, line={"color": colors[label], "width": 2.5}, fill="tozeroy")
    for figure, y_title in [(net_figure, "共同区间累计净值"), (drawdown_figure, "回撤")]:
        figure.update_layout(xaxis_title=None, yaxis_title=y_title, legend_title=None, margin={"l": 20, "r": 20, "t": 15, "b": 20})
        figure.update_xaxes(dtick="M12", tickformat="%Y", minor={"dtick": "M1", "ticks": "outside", "ticklen": 3, "showgrid": False})
    drawdown_figure.update_yaxes(tickformat=".0%")
    return net_figure, drawdown_figure


def comparison_analysis(metric_raw: pd.DataFrame, common_curves: pd.DataFrame) -> dict[str, object]:
    winners = metric_raw.set_index("key")["preferred"].to_dict() if not metric_raw.empty else {}
    a_count = sum(value == "实验A" for value in winners.values())
    b_count = sum(value == "实验B" for value in winners.values())
    if a_count > b_count:
        status = "实验A综合维度暂时占优"
    elif b_count > a_count:
        status = "实验B综合维度暂时占优"
    else:
        status = "两组实验各有优势"

    details = []
    return_winner = winners.get("annualized_return", "数据不足")
    risk_winners = [winners.get("annualized_volatility"), winners.get("max_drawdown")]
    signal_winner = winners.get("rank_icir", "数据不足")
    efficiency_winner = winners.get("average_turnover", "数据不足")
    details.append(f"收益维度：{return_winner}的历史年化收益相对更高。" if return_winner in {"实验A", "实验B"} else "收益维度：数据不足或大致相同。")
    if risk_winners[0] == risk_winners[1] and risk_winners[0] in {"实验A", "实验B"}:
        details.append(f"风险维度：{risk_winners[0]}同时具有较低波动和较小最大回撤。")
    else:
        details.append("风险维度：波动率与最大回撤未指向同一实验，需要结合自身承受能力判断。")
    details.append(f"因子有效性：{signal_winner}的Rank ICIR相对更高。" if signal_winner in {"实验A", "实验B"} else "因子有效性：两组接近或数据不足。")
    details.append(f"交易效率：{efficiency_winner}的月均换手率相对更低。" if efficiency_winner in {"实验A", "实验B"} else "交易效率：两组接近或数据不足。")
    if not common_curves.empty:
        details.append(f"公平区间：已在 {common_curves['month_end'].min().date()} 至 {common_curves['month_end'].max().date()} 的共同月份重新计算净值与回撤。")
    else:
        details.append("公平区间：两组实验没有足够的共同回测月份，不能直接比较净值曲线。")
    return {
        "status": status,
        "summary": "这是历史研究维度的综合比较，不是未来收益预测；批准前应优先复核Rank IC稳定性、回撤、换手和共同区间表现。",
        "details": details,
    }
