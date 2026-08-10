from __future__ import annotations

import pandas as pd
import streamlit as st

from app.charts import factor_correlation_chart
from app.config import (
    DEFAULT_DB_PATH,
    FACTOR_LABELS,
    MODEL_FACTOR_GROUPS,
    MODEL_FACTOR_WEIGHTS,
    MODEL_LABELS,
    MODEL_YAHOO_10,
)
from app.research_pipeline import compute_and_store_features, load_feature_panel
from app.scoring import validate_weights
from app.ui import empty_state, setup_page


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
if st.button("计算并保存月度因子", type="primary", disabled=not valid):
    bar, status = st.progress(0.0), st.empty()
    def progress(done, total, month):
        bar.progress(done / max(total, 1)); status.caption(f"月末 {pd.Timestamp(month).date()}（{done}/{total}）")
    try:
        panel = compute_and_store_features(
            DEFAULT_DB_PATH,
            weights,
            progress,
            model_name=model_name,
        )
        if panel.empty:
            empty_state("价格历史不足 252 个交易日，尚不能计算月末因子。")
        else:
            st.success(f"已计算并保存 {len(panel):,} 个股票—月份快照。")
    except Exception as exc:
        st.error(str(exc))

panel = load_feature_panel(DEFAULT_DB_PATH, model_name)
if panel.empty:
    empty_state()
else:
    latest_month = panel["month_end"].max()
    latest = panel[panel["month_end"] == latest_month]
    a, b, c = st.columns(3)
    a.metric("最新因子月", latest_month.date().isoformat())
    b.metric("有效股票", latest["model_score"].notna().sum())
    c.metric("平均覆盖率", f"{latest['factor_coverage'].mean():.1%}")
    st.dataframe(latest.sort_values("model_score", ascending=False), use_container_width=True, hide_index=True)
    st.plotly_chart(factor_correlation_chart(latest, list(default_weights)), use_container_width=True)
st.markdown("#### 公式边界")
st.write("股息率使用已除息现金分红与未复权月末价格；价格收益与波动率使用复权价格。日频波动稳定度代理因子来自日线滚动波动率，不是参考文章的分钟级高频因子。财务数据仅在 published_date 不晚于因子月末时使用。")
