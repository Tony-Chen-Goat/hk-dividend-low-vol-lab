from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


PALETTE = {"green": "#164E3B", "mint": "#88A894", "cream": "#F6F1E7", "orange": "#C76D2E", "red": "#A84032"}


def equity_curve_chart(monthly: pd.DataFrame):
    value_columns = [column for column in monthly if column.endswith("_value")]
    fig = px.line(monthly, x="month_end", y=value_columns, color_discrete_sequence=[PALETTE["green"], PALETTE["mint"], PALETTE["orange"], "#5B6E9B"])
    fig.update_layout(yaxis_title="累计净值", xaxis_title=None, legend_title=None)
    return fig


def rank_ic_chart(monthly: pd.DataFrame):
    fig = go.Figure()
    fig.add_bar(x=monthly["month_end"], y=monthly["rank_ic"], name="月度 Rank IC", marker_color=PALETTE["green"])
    if "rolling_12m_ic" in monthly:
        fig.add_scatter(x=monthly["month_end"], y=monthly["rolling_12m_ic"], name="滚动12月均值", line={"color": PALETTE["orange"], "width": 3})
    fig.update_layout(yaxis_title="Spearman 相关系数", xaxis_title=None)
    return fig


def factor_correlation_chart(frame: pd.DataFrame, factors: list[str]):
    correlation = frame[[column for column in factors if column in frame]].corr(method="spearman")
    return px.imshow(correlation, color_continuous_scale=[[0, PALETTE["red"]], [0.5, PALETTE["cream"]], [1, PALETTE["green"]]], zmin=-1, zmax=1, aspect="auto")
