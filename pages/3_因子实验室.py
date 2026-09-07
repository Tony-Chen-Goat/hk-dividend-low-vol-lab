from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from app.config import (
    DEFAULT_DB_PATH,
    FACTOR_LABELS,
    MODEL_FACTOR_GROUPS,
    MODEL_FACTOR_WEIGHTS,
    MODEL_LABELS,
    MODEL_YAHOO_10,
)
from app.database import load_setting
from app.display import localized_csv, localized_frame, stable_html_table
from app.experiment_store import experiment_display_name, get_experiment, next_experiment_version_name
from app.research_pipeline import available_experiments, compute_and_store_features, load_feature_panel
from app.scoring import validate_weights
from app.cloud_ui import persist_cloud_database
from app.page_runtime import setup_page
from app.ui import empty_state


def _correlation_color(value: float) -> tuple[str, str]:
    red = (168, 64, 50)
    cream = (246, 241, 231)
    green = (22, 78, 59)
    if pd.isna(value):
        return "#E7EBE8", "#65746D"
    bounded = max(-1.0, min(1.0, float(value)))
    start, end, ratio = (red, cream, bounded + 1.0) if bounded < 0 else (cream, green, bounded)
    rgb = tuple(round(left + (right - left) * ratio) for left, right in zip(start, end))
    luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return "#" + "".join(f"{channel:02X}" for channel in rgb), "#FFFFFF" if luminance < 145 else "#1C2A25"


def _stable_correlation_svg(frame: pd.DataFrame, factors: list[str]) -> str:
    """Keep the renderer page-local so hot deploys cannot retain an older shared module."""
    columns = [column for column in factors if column in frame.columns]
    if not columns:
        return '<div style="padding:1rem;border:1px solid #D9DED8;border-radius:.55rem">暂无可计算的因子相关性。</div>'

    correlation = frame[columns].apply(pd.to_numeric, errors="coerce").corr(method="spearman")
    labels = [FACTOR_LABELS.get(column, column) for column in columns]
    cell_size, left_margin, top_margin, bottom_margin = 58, 190, 180, 44
    width = left_margin + cell_size * len(columns) + 24
    height = top_margin + cell_size * len(columns) + bottom_margin
    elements = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
        'aria-label="因子 Spearman 相关性热力图" xmlns="http://www.w3.org/2000/svg">',
        '<text x="12" y="25" fill="#1C2A25" font-size="16" font-weight="700">因子 Spearman 相关性</text>',
        '<text x="12" y="48" fill="#65746D" font-size="12">-1 为反向，0 为弱相关，+1 为同向</text>',
    ]
    for index, label in enumerate(labels):
        # Start each rotated label above its own cell.  With ``text-anchor=start``
        # the glyphs extend up and to the right instead of descending behind the
        # first heatmap row (the previous ``end`` anchor caused the overlap).
        x = left_margin + index * cell_size + 12
        y = top_margin - 14
        safe_label = escape(str(label), quote=True)
        elements.append(
            f'<text x="{x:.1f}" y="{y}" fill="#44534D" font-size="11" text-anchor="start" '
            f'transform="rotate(-48 {x:.1f} {y})">{safe_label}</text>'
        )
        row_y = top_margin + index * cell_size + cell_size / 2 + 4
        elements.append(
            f'<text x="{left_margin - 10}" y="{row_y:.1f}" fill="#44534D" font-size="11" '
            f'text-anchor="end">{safe_label}</text>'
        )

    for row_index, row_column in enumerate(columns):
        for column_index, column in enumerate(columns):
            value = correlation.loc[row_column, column]
            fill, text_color = _correlation_color(value)
            x = left_margin + column_index * cell_size
            y = top_margin + row_index * cell_size
            label = "—" if pd.isna(value) else f"{float(value):.2f}"
            elements.extend([
                f'<rect x="{x}" y="{y}" width="{cell_size - 2}" height="{cell_size - 2}" rx="4" fill="{fill}" />',
                f'<text x="{x + cell_size / 2:.1f}" y="{y + cell_size / 2 + 4:.1f}" '
                f'fill="{text_color}" font-size="11" font-weight="600" text-anchor="middle">{label}</text>',
            ])
    elements.append("</svg>")
    return (
        '<div style="overflow:auto;background:#FFFDF8;border:1px solid #D9DED8;border-radius:.55rem;padding:.7rem">'
        + "".join(elements)
        + "</div>"
    )


setup_page("因子实验室", "🧪")
st.caption("连续型因子按月独立进行 1%/99% 缩尾和百分位评分；低波、回撤、下行波动与日频波动 CV 采用反向排名。")
model_name = st.selectbox(
    "因子模式",
    list(MODEL_LABELS),
    format_func=MODEL_LABELS.get,
)
if model_name == MODEL_YAHOO_10:
    st.info("当前模式只使用 Yahoo 可稳定取得的价格、成交量和现金分红数据，不要求财务报表或自由流通股本。")
factor_groups = MODEL_FACTOR_GROUPS[model_name]
default_weights = MODEL_FACTOR_WEIGHTS[model_name]
weights = {}
for group, factors in factor_groups.items():
    with st.expander(group, expanded=True):
        columns = st.columns(min(4, len(factors)))
        for index, factor in enumerate(factors):
            weights[factor] = columns[index % len(columns)].number_input(
                FACTOR_LABELS[factor],
                0.0,
                1.0,
                default_weights[factor],
                0.01,
                format="%.2f",
                key=f"weight_{model_name}_{factor}",
            )
valid, delta = validate_weights(weights)
st.metric("权重合计", f"{sum(weights.values()):.0%}")
if not valid:
    st.error(f"权重不等于100%，禁止运行。需{'增加' if delta > 0 else '减少'} {abs(delta):.1%}。")
next_version = next_experiment_version_name(DEFAULT_DB_PATH)
st.info(f"本次实验将自动命名为：{next_version}。同一天继续创建时，版本序号会自动递增。")
experiment_note = st.text_input(
    "实验备注",
    value="默认权重" if model_name == MODEL_YAHOO_10 else "完整13因子",
    help="填写本次调整目的，例如“提高低波权重”或“5只集中组合”；系统版本名称不能手动修改。",
)
risk_settings = load_setting(f"risk_filter_{model_name}", {}, DEFAULT_DB_PATH) or {}
if risk_settings:
    st.success("已读取“股票池与风险过滤”页面保存的规则；系统会在每个月末先过滤，再计算因子。")
else:
    st.warning("尚未保存该模式的风险过滤规则，将使用系统默认规则。建议先到“股票池与风险过滤”检查并保存。")
if st.button("创建新实验并计算月度因子", type="primary", disabled=not valid):
    bar, status = st.progress(0.0), st.empty()
    def progress(done, total, month):
        bar.progress(done / max(total, 1)); status.caption(f"月末 {pd.Timestamp(month).date()}（{done}/{total}）")
    try:
        panel = compute_and_store_features(
            DEFAULT_DB_PATH,
            weights,
            progress,
            model_name=model_name,
            experiment_name=experiment_note.strip() or "未填写备注",
            risk_settings=risk_settings,
        )
        if panel.empty:
            empty_state("价格历史不足 252 个交易日，尚不能计算月末因子。")
        else:
            experiment_id = str(panel["experiment_id"].iloc[0])
            st.session_state["active_experiment_id"] = experiment_id
            persist_cloud_database("factor_experiment_completed")
            st.success(f"实验 {experiment_id} 已创建，保存 {len(panel):,} 个风险过滤后股票—月份快照。后续Rank IC与月度回测请选择同一实验编号。")
    except Exception as exc:
        st.error(str(exc))

experiments = available_experiments(DEFAULT_DB_PATH)
model_experiments = experiments[experiments["model_name"] == model_name] if not experiments.empty else experiments
if model_experiments.empty:
    panel = pd.DataFrame()
    selected_experiment = None
else:
    options = model_experiments["experiment_id"].astype(str).tolist()
    preferred = st.session_state.get("active_experiment_id")
    index = options.index(preferred) if preferred in options else 0
    selected_experiment = st.selectbox(
        "查看已保存实验",
        options,
        index=index,
        format_func=lambda value: f"{experiment_display_name(model_experiments.set_index('experiment_id').loc[value])} · {value}",
    )
    panel = load_feature_panel(
        DEFAULT_DB_PATH, model_name, selected_experiment, latest_only=True
    )
if panel.empty:
    empty_state()
else:
    latest_month = panel["month_end"].max()
    latest = panel[panel["month_end"] == latest_month]
    a, b, c = st.columns(3)
    a.metric("最新因子月", latest_month.date().isoformat())
    b.metric("有效股票", latest["model_score"].notna().sum())
    c.metric("平均覆盖率", f"{latest['factor_coverage'].mean():.1%}")
    experiment = get_experiment(selected_experiment, DEFAULT_DB_PATH)
    st.caption(f"实验编号：{selected_experiment}　·　状态：{experiment.get('status')}　·　该版本会被Rank IC、月度回测和最新选股按编号读取。")
    latest_sorted = latest.sort_values("model_score", ascending=False)
    st.markdown("#### 最新因子截面")
    st.markdown(stable_html_table(localized_frame(latest_sorted)), unsafe_allow_html=True)
    st.download_button(
        "下载最新因子截面 CSV",
        localized_csv(latest_sorted),
        file_name=f"factor_snapshot_{selected_experiment}_{latest_month.date().isoformat()}.csv",
        mime="text/csv",
        on_click="ignore",
    )
    st.markdown("#### 因子相关性")
    st.markdown(_stable_correlation_svg(latest, list(default_weights)), unsafe_allow_html=True)
st.markdown("#### 公式边界")
st.write("股息率使用已除息现金分红与未复权月末价格；价格收益与波动率使用复权价格。日频波动稳定度代理因子来自日线滚动波动率，不是参考文章的分钟级高频因子。财务数据仅在 published_date 不晚于因子月末时使用。")
