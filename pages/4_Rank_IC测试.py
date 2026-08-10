from __future__ import annotations

import pandas as pd
import streamlit as st

from app.charts import rank_ic_chart
from app.config import DEFAULT_DB_PATH, FACTOR_LABELS, MODEL_FACTOR_WEIGHTS, MODEL_LABELS
from app.rank_ic import compare_factor_ics, ic_summary, monthly_rank_ic
from app.research_pipeline import available_feature_models, load_feature_panel
from app.ui import empty_state, setup_page


setup_page("Rank IC 测试", "📐")
available_models = available_feature_models(DEFAULT_DB_PATH)
if not available_models:
    empty_state("尚无月度因子与下一月收益。请先在因子实验室执行计算。")
    st.stop()
model_name = st.selectbox(
    "因子模式",
    available_models,
    format_func=MODEL_LABELS.get,
)
panel = load_feature_panel(DEFAULT_DB_PATH, model_name)
if panel.empty or "forward_return" not in panel:
    empty_state("尚无月度因子与下一月收益。请先在因子实验室执行计算。")
    st.stop()

minimum = st.number_input("单月最少有效股票", 3, 100, 5)
monthly = monthly_rank_ic(panel, "model_score", "forward_return", int(minimum))
summary = ic_summary(monthly)
st.markdown('<span class="oos-tag">必须结合样本外窗口解读</span>', unsafe_allow_html=True)
cols = st.columns(5)
cols[0].metric("平均 Rank IC", f"{summary['mean_rank_ic']:.3f}" if pd.notna(summary["mean_rank_ic"]) else "—")
cols[1].metric("Rank ICIR", f"{summary['rank_icir']:.2f}" if pd.notna(summary["rank_icir"]) else "—")
cols[2].metric("年化 ICIR", f"{summary['annualized_rank_icir']:.2f}" if pd.notna(summary["annualized_rank_icir"]) else "—")
cols[3].metric("IC 正值比例", f"{summary['positive_ratio']:.1%}" if pd.notna(summary["positive_ratio"]) else "—")
cols[4].metric("最近12月 IC", f"{summary['latest_12m_rank_ic']:.3f}" if pd.notna(summary["latest_12m_rank_ic"]) else "—")
st.plotly_chart(rank_ic_chart(monthly), use_container_width=True)
st.dataframe(monthly, use_container_width=True, hide_index=True)

active_weights = MODEL_FACTOR_WEIGHTS[model_name]
st.markdown(f"#### {len(active_weights)} 个子因子比较")
score_columns = [f"{factor}__score" for factor in active_weights]
comparison = compare_factor_ics(panel, score_columns)
comparison["因子"] = comparison["factor"].str.replace("__score", "", regex=False).map(FACTOR_LABELS)
st.dataframe(comparison.drop(columns="factor"), use_container_width=True, hide_index=True)
st.caption("每个月使用当月全部有效股票计算 Spearman 相关，不限于最终入选股票；有效样本太少时跳过并保留原因。")
