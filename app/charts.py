from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


PALETTE = {"green": "#164E3B", "mint": "#88A894", "cream": "#F6F1E7", "orange": "#C76D2E", "red": "#A84032"}

EQUITY_CURVE_LABELS = {
    "net_value": "扣费后组合净值",
    "gross_value": "扣费前组合净值",
    "恒生指数_value": "恒生指数",
    "恒生中国企业指数_value": "恒生国企指数",
}

EQUITY_CURVE_STYLES = {
    "net_value": {"color": PALETTE["green"], "width": 3.2},
    "gross_value": {"color": PALETTE["mint"], "width": 2.4},
    "恒生指数_value": {"color": PALETTE["orange"], "width": 2.2},
    "恒生中国企业指数_value": {"color": "#5B6E9B", "width": 2.2},
}


def equity_curve_chart(monthly: pd.DataFrame):
    data = monthly.copy()
    data["month_end"] = pd.to_datetime(data["month_end"])
    value_columns = [column for column in data if column.endswith("_value")]
    fig = go.Figure()
    for index, column in enumerate(value_columns):
        label = EQUITY_CURVE_LABELS.get(column, column.removesuffix("_value"))
        style = EQUITY_CURVE_STYLES.get(
            column,
            {"color": [PALETTE["green"], PALETTE["mint"], PALETTE["orange"], "#5B6E9B"][index % 4], "width": 2.2},
        )
        is_net_curve = column == "net_value"
        fig.add_trace(
            go.Scatter(
                x=data["month_end"],
                y=pd.to_numeric(data[column], errors="coerce"),
                name=label,
                mode="lines+markers" if is_net_curve else "lines",
                line=style,
                marker={
                    "size": 7,
                    "color": style["color"],
                    "line": {"color": "#FFFFFF", "width": 1},
                } if is_net_curve else None,
                connectgaps=False,
                customdata=data["month_end"].dt.strftime("%Y年%m月").to_numpy().reshape(-1, 1),
                hovertemplate=f"{label}<br>%{{customdata[0]}}<br>累计净值：%{{y:.3f}}<extra></extra>",
            )
        )
    fig.update_layout(
        yaxis_title="累计净值",
        xaxis_title=None,
        legend_title=None,
        hovermode="closest",
        clickmode="event+select",
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
    )
    fig.update_xaxes(
        dtick="M12",
        tickformat="%Y",
        ticks="outside",
        ticklen=8,
        showgrid=True,
        gridcolor="rgba(22, 78, 59, 0.10)",
        minor={
            "dtick": "M1",
            "ticks": "outside",
            "ticklen": 4,
            "showgrid": False,
        },
    )
    fig.update_yaxes(gridcolor="rgba(22, 78, 59, 0.10)", zeroline=False)
    return fig


def selected_month_from_chart_event(event) -> pd.Timestamp | None:
    """Extract a clicked Plotly point month from Streamlit's selection state."""
    if event is None:
        return None
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    points = getattr(selection, "points", None)
    if points is None and isinstance(selection, dict):
        points = selection.get("points")
    if not points:
        return None
    point = points[0]
    x_value = point.get("x") if isinstance(point, dict) else getattr(point, "x", None)
    selected = pd.to_datetime(x_value, errors="coerce")
    return None if pd.isna(selected) else pd.Timestamp(selected)


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
