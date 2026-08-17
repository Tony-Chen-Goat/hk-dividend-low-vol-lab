from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


PALETTE = {
    "green": "#164E3B",
    "mint": "#88A894",
    "orange": "#C76D2E",
    "blue": "#5B6E9B",
}

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
    "恒生中国企业指数_value": {"color": PALETTE["blue"], "width": 2.2},
}


def available_chart_months(monthly: pd.DataFrame) -> list[str]:
    """Return sorted real months that can be displayed by the equity chart."""
    if monthly.empty or "month_end" not in monthly:
        return []
    dates = pd.to_datetime(monthly["month_end"], errors="coerce").dropna()
    return sorted(dates.dt.to_period("M").astype(str).unique().tolist())


def default_chart_window(
    monthly: pd.DataFrame,
    years: int | None = 10,
    today: pd.Timestamp | str | None = None,
) -> tuple[str | None, str | None]:
    """Choose a real-data window ending no later than today.

    A finite ``years`` value starts from January of ``today.year - years``.
    Missing boundary months are clamped to the nearest month that actually
    exists in the saved backtest, so the UI never invents observations.
    """
    months = available_chart_months(monthly)
    if not months:
        return None, None

    month_periods = pd.PeriodIndex(months, freq="M")
    current = pd.Period(pd.Timestamp(today) if today is not None else pd.Timestamp.today(), freq="M")
    not_future = month_periods[month_periods <= current]
    end_period = not_future[-1] if len(not_future) else month_periods[-1]

    if years is None:
        start_period = month_periods[0]
    else:
        requested_start = pd.Period(year=current.year - int(years), month=1, freq="M")
        eligible = month_periods[(month_periods >= requested_start) & (month_periods <= end_period)]
        start_period = eligible[0] if len(eligible) else month_periods[0]

    if start_period > end_period:
        start_period = month_periods[0]
    return str(start_period), str(end_period)


def chart_input_window(
    monthly: pd.DataFrame,
    years: int | None = 10,
    today: pd.Timestamp | str | None = None,
    earliest_month: str = "2016-01",
) -> tuple[str | None, str | None]:
    """Return calendar input defaults with a hard lower month boundary."""
    months = available_chart_months(monthly)
    if not months:
        return None, None

    current = pd.Period(pd.Timestamp(today) if today is not None else pd.Timestamp.today(), freq="M")
    floor = pd.Period(earliest_month, freq="M")
    _, latest_month = default_chart_window(monthly, years=None, today=today)
    end_period = pd.Period(latest_month, freq="M")
    if years is None:
        requested_start = pd.Period(months[0], freq="M")
    else:
        requested_start = pd.Period(year=current.year - int(years), month=1, freq="M")
    start_period = max(floor, requested_start)
    return str(start_period), str(end_period)


def filter_chart_window(monthly: pd.DataFrame, start_month: str, end_month: str) -> pd.DataFrame:
    """Filter saved monthly rows by inclusive calendar month without rebasing values."""
    if monthly.empty or "month_end" not in monthly:
        return monthly.copy()
    data = monthly.copy()
    dates = pd.to_datetime(data["month_end"], errors="coerce")
    periods = dates.dt.to_period("M")
    start_period, end_period = pd.Period(start_month, freq="M"), pd.Period(end_month, freq="M")
    return data.loc[dates.notna() & periods.between(start_period, end_period)].copy()


def equity_curve_chart(monthly: pd.DataFrame):
    data = monthly.copy()
    data["month_end"] = pd.to_datetime(data["month_end"])
    value_columns = [column for column in data if column.endswith("_value")]
    colors = [PALETTE["green"], PALETTE["mint"], PALETTE["orange"], PALETTE["blue"]]
    fig = go.Figure()
    for index, column in enumerate(value_columns):
        label = EQUITY_CURVE_LABELS.get(column, column.removesuffix("_value"))
        style = EQUITY_CURVE_STYLES.get(column, {"color": colors[index % 4], "width": 2.2})
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
        minor={"dtick": "M1", "ticks": "outside", "ticklen": 4, "showgrid": False},
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
