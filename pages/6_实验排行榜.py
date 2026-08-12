from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app.config import DEFAULT_DB_PATH, FACTOR_LABELS, MODEL_LABELS
from app.display import localized_csv, localized_frame
from app.experiment_store import import_experiments_csv, list_experiments
from app.ui import empty_state, setup_page


setup_page("实验排行榜", "🏁")
st.markdown("#### 原理与作用")
st.write("实验排行榜集中保存参数调优产生的候选方案，并按统一的样本外综合得分排序。它用于比较因子权重、Rank ICIR、收益、回撤、换手率和数据覆盖率，避免只记住表现最好的一次实验。")
st.info("排行榜第一名只是历史验证窗口中的相对优胜方案，不等于未来最佳策略。选择方案后仍需返回因子实验室重新计算，并通过Rank IC、月度组合回测及人工风险复核。")
experiments = list_experiments(DEFAULT_DB_PATH)
if experiments.empty:
    empty_state("尚未保存实验。请先前往参数调优页运行样本外实验。")
else:
    model_options = [name for name in MODEL_LABELS if name in set(experiments["model_name"].dropna())]
    selected_model = st.selectbox(
        "因子模式",
        ["all", *model_options],
        format_func=lambda value: "全部模式" if value == "all" else MODEL_LABELS[value],
    )
    if selected_model != "all":
        experiments = experiments[experiments["model_name"] == selected_model].copy()
    sort_label = st.selectbox("排序指标", ["综合得分", "Rank ICIR", "年化收益", "最大回撤", "月均换手率"])
    sort_map = {"综合得分": ("score", False), "Rank ICIR": ("rank_icir", False), "年化收益": ("annualized_return", False), "最大回撤": ("max_drawdown", True), "月均换手率": ("average_turnover", True)}
    key, ascending = sort_map[sort_label]
    if key in experiments:
        experiments = experiments.sort_values(key, ascending=ascending)
    st.markdown('<span class="oos-tag">只按样本外结果进行最终排名</span>', unsafe_allow_html=True)
    st.dataframe(localized_frame(experiments), use_container_width=True, hide_index=True)
    export_cols = st.columns(2)
    export_cols[0].download_button("导出标准字段CSV", experiments.to_csv(index=False).encode("utf-8-sig"), "experiments.csv")
    export_cols[1].download_button("导出中文字段CSV", localized_csv(experiments), "experiments_cn.csv")
    st.markdown("#### 两组实验对比")
    choices = experiments["experiment_id"].tolist()
    if len(choices) >= 2:
        left, right = st.columns(2)
        a = left.selectbox("实验 A", choices, index=0)
        b = right.selectbox("实验 B", choices, index=1)
        row_a = experiments.set_index("experiment_id").loc[a]
        row_b = experiments.set_index("experiment_id").loc[b]
        weights_a = json.loads(row_a.get("factor_weights_json") or "{}")
        weights_b = json.loads(row_b.get("factor_weights_json") or "{}")
        comparison = pd.DataFrame({"实验 A": weights_a, "实验 B": weights_b}).fillna(0)
        comparison["差异"] = comparison["实验 B"] - comparison["实验 A"]
        comparison.index = [FACTOR_LABELS.get(index, index) for index in comparison.index]
        st.dataframe(comparison.rename_axis("因子"), use_container_width=True)
    else:
        st.info("至少保存两组实验后可比较因子权重差异。")

st.markdown("#### 导入历史实验")
uploaded = st.file_uploader("实验 CSV", type=["csv"])
if uploaded and st.button("导入实验"):
    try:
        count = import_experiments_csv(pd.read_csv(uploaded), DEFAULT_DB_PATH)
        st.success(f"已导入或更新 {count} 条实验记录。")
    except Exception as exc:
        st.error(str(exc))
