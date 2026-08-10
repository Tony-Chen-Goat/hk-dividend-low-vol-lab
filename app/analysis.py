from __future__ import annotations

import numpy as np
import pandas as pd


def rank_ic_analysis(summary: dict[str, float], monthly: pd.DataFrame) -> dict[str, object]:
    values = pd.to_numeric(monthly.get("rank_ic", pd.Series(dtype=float)), errors="coerce").dropna()
    if values.empty:
        return {
            "status": "数据不足",
            "summary": "没有足够的有效月份形成Rank IC结论。",
            "details": ["请检查因子得分、下一月收益和单月有效股票数量。"],
        }

    mean = summary.get("mean_rank_ic", np.nan)
    icir = summary.get("rank_icir", np.nan)
    positive = summary.get("positive_ratio", np.nan)
    recent = summary.get("latest_12m_rank_ic", np.nan)

    if mean >= 0.05:
        direction = "历史平均排序信号较明显为正"
    elif mean >= 0.02:
        direction = "历史平均排序信号为弱正向"
    elif mean > 0:
        direction = "历史平均排序信号仅轻微为正"
    elif mean > -0.02:
        direction = "历史平均排序信号接近无效"
    else:
        direction = "历史平均排序信号为负向"

    if pd.isna(icir):
        stability = "稳定性无法计算"
    elif icir >= 0.5:
        stability = "月度信号相对稳定"
    elif icir >= 0.2:
        stability = "月度信号具有一定稳定性"
    elif icir >= 0:
        stability = "月度波动较大，稳定性偏弱"
    else:
        stability = "月度信号方向和稳定性均需警惕"

    if pd.isna(recent) or pd.isna(mean):
        trend = "近期趋势无法判断"
    elif recent > mean + 0.02:
        trend = "最近12个月强于长期平均，近期有所改善"
    elif recent < mean - 0.02:
        trend = "最近12个月弱于长期平均，近期有所转弱"
    else:
        trend = "最近12个月与长期平均大致一致"

    if mean >= 0.02 and icir >= 0.2 and positive >= 0.55:
        status = "信号相对稳定"
    elif mean > 0 and recent > 0:
        status = "信号偏弱，继续观察"
    else:
        status = "信号方向异常或证据不足"

    skipped = int(monthly["rank_ic"].isna().sum()) if "rank_ic" in monthly else 0
    details = [
        f"{direction}；{stability}。",
        f"{trend}。",
        f"有效月份 {len(values)} 个，IC为正的月份占 {positive:.1%}。" if pd.notna(positive) else f"有效月份 {len(values)} 个。",
    ]
    if skipped:
        details.append(f"另有 {skipped} 个月因样本太少或横截面无变化而跳过。")
    return {
        "status": status,
        "summary": f"平均Rank IC为 {mean:.3f}，Rank ICIR为 {icir:.2f}。" if pd.notna(icir) else f"平均Rank IC为 {mean:.3f}。",
        "details": details,
    }


def backtest_analysis(
    metrics: dict[str, float],
    monthly: pd.DataFrame,
    benchmark_returns: pd.Series | None = None,
) -> dict[str, object]:
    returns = pd.to_numeric(monthly.get("net_return", pd.Series(dtype=float)), errors="coerce").dropna()
    if returns.empty:
        return {
            "status": "数据不足",
            "summary": "没有足够的组合月收益形成回测结论。",
            "details": ["请检查下一月收益和完整因子覆盖。"],
            "diagnostics": {},
        }

    annualized = metrics.get("annualized_return", np.nan)
    sharpe = metrics.get("sharpe", np.nan)
    max_drawdown = metrics.get("max_drawdown", np.nan)
    turnover = metrics.get("average_turnover", np.nan)
    cost_drag = metrics.get("gross_total_return", np.nan) - metrics.get("net_total_return", np.nan)
    worst_month = float(returns.min())
    recent = returns.tail(12)
    recent_return = float((1 + recent).prod() - 1)

    benchmark_annualized = np.nan
    if benchmark_returns is not None:
        benchmark = pd.to_numeric(benchmark_returns, errors="coerce").dropna()
        if not benchmark.empty:
            total = float((1 + benchmark).prod() - 1)
            benchmark_annualized = float((1 + total) ** (12 / len(benchmark)) - 1)

    if annualized > 0 and sharpe >= 0.5 and max_drawdown <= 0.30:
        status = "历史表现相对稳健"
    elif annualized > 0:
        status = "存在正收益，但风险或稳定性需观察"
    else:
        status = "历史回测结果偏弱"

    details = [
        f"组合年化收益为 {annualized:.1%}，年化波动率为 {metrics.get('annualized_volatility', np.nan):.1%}。",
        f"历史最大回撤为 {max_drawdown:.1%}，最差单月收益为 {worst_month:.1%}。",
        f"夏普比率为 {sharpe:.2f}，月均换手率为 {turnover:.1%}。",
        f"最近12个月累计收益为 {recent_return:.1%}；估算交易成本拖累累计收益约 {cost_drag:.1%}。",
    ]
    if pd.notna(benchmark_annualized):
        relative = annualized - benchmark_annualized
        details.append(f"基准年化收益约为 {benchmark_annualized:.1%}，组合年化收益差约为 {relative:+.1%}。")
    return {
        "status": status,
        "summary": "结果用于检验评分、权重、约束和交易成本共同作用后的历史组合表现。",
        "details": details,
        "diagnostics": {
            "最近12月累计收益": recent_return,
            "最差单月收益": worst_month,
            "交易成本累计拖累": cost_drag,
            "基准年化收益": benchmark_annualized,
        },
    }
