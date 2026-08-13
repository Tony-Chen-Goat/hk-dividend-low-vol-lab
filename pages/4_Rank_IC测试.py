from __future__ import annotations

import pandas as pd
import streamlit as st

from app.analysis import rank_ic_analysis
from app.charts import rank_ic_chart
from app.config import DEFAULT_DB_PATH, FACTOR_LABELS, MODEL_LABELS
from app.display import localized_frame
from app.experiment_store import experiment_display_name, get_experiment, store_rank_ic_results
from app.rank_ic import compare_factor_ics, ic_summary, monthly_rank_ic
from app.research_pipeline import available_experiments, load_feature_panel
from app.ui import empty_state, setup_page


setup_page("Rank IC 测试", "📐")
experiments = available_experiments(DEFAULT_DB_PATH)
if experiments.empty:
    empty_state("尚无月度因子与下一月收益。请先在因子实验室执行计算。")
    st.stop()
experiment_options = experiments["experiment_id"].astype(str).tolist()
preferred = st.session_state.get("active_experiment_id")
index = experiment_options.index(preferred) if preferred in experiment_options else 0
experiment_id = st.selectbox(
    "选择实验版本",
    experiment_options,
    index=index,
    format_func=lambda value: f"{experiment_display_name(experiments.set_index('experiment_id').loc[value])} · {MODEL_LABELS.get(experiments.set_index('experiment_id').loc[value, 'model_name'], experiments.set_index('experiment_id').loc[value, 'model_name'])} · {value}",
)
st.session_state["active_experiment_id"] = experiment_id
experiment = get_experiment(experiment_id, DEFAULT_DB_PATH)
model_name = experiment["model_name"]
panel = load_feature_panel(DEFAULT_DB_PATH, model_name, experiment_id)
if panel.empty or "forward_return" not in panel:
    empty_state("尚无月度因子与下一月收益。请先在因子实验室执行计算。")
    st.stop()

locked = bool(experiment.get("approved"))
saved_minimum = int((experiment.get("metrics") or {}).get("rank_ic_minimum", 5))
if locked:
    st.success("这是已经批准的正式实验。Rank IC设置已锁定；如需调整，请创建新的实验版本。")
minimum = st.number_input("单月最少有效股票", 3, 100, saved_minimum, disabled=locked)
monthly = monthly_rank_ic(panel, "model_score", "forward_return", int(minimum))
summary = ic_summary(monthly)
summary["rank_ic_minimum"] = int(minimum)
st.caption(f"实验编号：{experiment_id}。本页读取的是该实验已经冻结的因子权重和风险过滤后月度股票池，测试结果会回写到同一实验档案。")
st.markdown('<span class="oos-tag">必须结合样本外窗口解读</span>', unsafe_allow_html=True)
cols = st.columns(5)
cols[0].metric("平均 Rank IC", f"{summary['mean_rank_ic']:.3f}" if pd.notna(summary["mean_rank_ic"]) else "—")
cols[1].metric("Rank ICIR", f"{summary['rank_icir']:.2f}" if pd.notna(summary["rank_icir"]) else "—")
cols[2].metric("年化 ICIR", f"{summary['annualized_rank_icir']:.2f}" if pd.notna(summary["annualized_rank_icir"]) else "—")
cols[3].metric("IC 正值比例", f"{summary['positive_ratio']:.1%}" if pd.notna(summary["positive_ratio"]) else "—")
cols[4].metric("最近12月 IC", f"{summary['latest_12m_rank_ic']:.3f}" if pd.notna(summary["latest_12m_rank_ic"]) else "—")
st.plotly_chart(rank_ic_chart(monthly), use_container_width=True)
analysis = rank_ic_analysis(summary, monthly)
st.markdown("#### 通俗分析与研究结论")
st.info(f"{analysis['status']}：{analysis['summary']}")
for detail in analysis["details"]:
    st.write(f"- {detail}")
st.caption("结论使用固定、可复核的描述性分档，不是投资评级；仍需结合样本外测试与组合回测。")

st.markdown("#### 月度明细")
st.dataframe(localized_frame(monthly), use_container_width=True, hide_index=True)

active_weights = experiment.get("factor_weights") or {}
st.markdown(f"#### {len(active_weights)} 个子因子比较")
score_columns = [f"{factor}__score" for factor in active_weights]
comparison = compare_factor_ics(panel, score_columns)
store_rank_ic_results(experiment_id, monthly, summary, comparison, DEFAULT_DB_PATH)
comparison["因子"] = comparison["factor"].str.replace("__score", "", regex=False).map(FACTOR_LABELS)
st.dataframe(localized_frame(comparison.drop(columns="factor")), use_container_width=True, hide_index=True)
st.caption("每个月使用当月全部有效股票计算 Spearman 相关，不限于最终入选股票；有效样本太少时跳过并保留原因。")
