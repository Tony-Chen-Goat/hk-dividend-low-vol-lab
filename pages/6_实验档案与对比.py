from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import DEFAULT_DB_PATH, MODEL_LABELS
from app.database import read_table
from app.display import localized_csv, localized_frame
from app.experiment_comparison import (
    common_period_curves,
    common_period_figures,
    comparison_analysis,
    configuration_comparison,
    core_metric_comparison,
    factor_weight_comparison,
)
from app.experiment_store import approve_experiment, experiment_display_name, export_experiment_bundle, get_experiment, list_experiments
from app.ui import empty_state, setup_page


setup_page("实验档案与对比", "🗂️")
st.markdown("#### 原理与作用")
st.write("这里保存每一次手动因子实验的独立版本：权重、风险规则、Rank IC、月度回测、净值和调仓明细都通过实验编号绑定，旧实验不会被新实验覆盖。")
st.info("排名用于横向比较历史研究表现，不是未来收益预测。建议先看Rank IC稳定性、回撤、换手和数据覆盖，再比较净收益；不要只选历史收益最高的方案。当前手动全历史实验不自动等同于严格样本外结果。")
experiments = list_experiments(DEFAULT_DB_PATH)
if experiments.empty:
    empty_state("尚未保存实验。请先在因子实验室创建一轮手动实验，再完成Rank IC和月度组合回测。")
else:
    model_options = [name for name in MODEL_LABELS if name in set(experiments["model_name"].dropna())]
    selected_model = st.selectbox(
        "因子模式",
        ["all", *model_options],
        format_func=lambda value: "全部模式" if value == "all" else MODEL_LABELS[value],
    )
    if selected_model != "all":
        experiments = experiments[experiments["model_name"] == selected_model].copy()
    sort_label = st.selectbox("排序指标", ["综合得分", "Rank ICIR", "历史年化收益", "最大回撤", "月均换手率"])
    sort_map = {"综合得分": ("score", False), "Rank ICIR": ("rank_icir", False), "历史年化收益": ("annualized_return", False), "最大回撤": ("max_drawdown", True), "月均换手率": ("average_turnover", True)}
    key, ascending = sort_map[sort_label]
    if key in experiments:
        experiments = experiments.sort_values(key, ascending=ascending)
    st.markdown('<span class="oos-tag">历史研究表现，不代表预估收益</span>', unsafe_allow_html=True)
    st.dataframe(localized_frame(experiments), use_container_width=True, hide_index=True)
    export_cols = st.columns(2)
    export_cols[0].download_button("导出标准字段CSV", experiments.to_csv(index=False).encode("utf-8-sig"), "experiments.csv")
    export_cols[1].download_button("导出中文字段CSV", localized_csv(experiments), "experiments_cn.csv")
    st.markdown("#### 查看、下载与批准实验")
    selected = st.selectbox(
        "实验版本",
        experiments["experiment_id"].astype(str).tolist(),
        format_func=lambda value: f"{experiment_display_name(experiments.set_index('experiment_id').loc[value])} · {value}",
    )
    selected_record = get_experiment(selected, DEFAULT_DB_PATH)
    st.json({
        "实验编号": selected,
        "状态": selected_record.get("status"),
        "因子权重": selected_record.get("factor_weights"),
        "风险规则": selected_record.get("risk_settings"),
        "回测设置": selected_record.get("backtest_settings"),
        "研究指标": selected_record.get("metrics"),
        "数据说明": selected_record.get("quality_note"),
    })
    action_cols = st.columns(2)
    if action_cols[0].button("生成完整实验数据包 ZIP"):
        with st.spinner("正在按当前实验编号生成数据包……"):
            bundle = export_experiment_bundle(selected, DEFAULT_DB_PATH)
        action_cols[0].download_button(
            "下载完整实验数据包 ZIP",
            bundle,
            f"experiment_{selected}.zip",
            "application/zip",
            on_click="ignore",
        )
    if action_cols[1].button("批准为最新选股正式实验", type="primary"):
        if selected_record.get("status") != "completed":
            st.error("该实验尚未完成月度组合回测，不能批准。")
        elif "rank_icir" not in (selected_record.get("metrics") or {}):
            st.error("该实验尚未完成Rank IC测试，不能批准。")
        elif (selected_record.get("backtest_settings") or {}).get("portfolio_method") == "article":
            st.error("文章方案一基准只用于对照，不能批准为因子最新选股实验。请使用因子增强模型完成回测。")
        else:
            approve_experiment(selected, DEFAULT_DB_PATH)
            st.session_state["active_experiment_id"] = selected
            st.success("已批准。最新选股结果将只读取这个实验版本。")
    st.markdown("#### 两组实验对比")
    choices = experiments["experiment_id"].tolist()
    if len(choices) >= 2:
        left, right = st.columns(2)
        format_version = lambda value: f"{experiment_display_name(experiments.set_index('experiment_id').loc[value])} · {value}"
        a = left.selectbox("实验 A", choices, index=0, format_func=format_version)
        b = right.selectbox("实验 B", choices, index=1, format_func=format_version)
        if a == b:
            st.warning("请选择两个不同的实验版本进行比较。")
        else:
            record_a, record_b = get_experiment(str(a), DEFAULT_DB_PATH), get_experiment(str(b), DEFAULT_DB_PATH)
            st.caption(f"实验A：{record_a['display_name']}　｜　实验B：{record_b['display_name']}")

            core_display, core_raw = core_metric_comparison(record_a, record_b)
            st.markdown("##### 核心研究指标")
            st.dataframe(core_display, use_container_width=True, hide_index=True)

            config_display, config_raw = configuration_comparison(record_a, record_b)
            weight_display, weight_raw = factor_weight_comparison(record_a, record_b)
            config_tab, weight_tab = st.tabs(["组合与回测配置", "因子权重差异"])
            with config_tab:
                st.dataframe(config_display, use_container_width=True, hide_index=True)
            with weight_tab:
                st.dataframe(
                    weight_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "实验A": st.column_config.NumberColumn(format="percent"),
                        "实验B": st.column_config.NumberColumn(format="percent"),
                        "差异（B-A）": st.column_config.NumberColumn(format="percent"),
                    },
                )

            backtests = read_table(
                "backtest_monthly", DEFAULT_DB_PATH,
                filters={"experiment_id": [str(a), str(b)]},
            )
            curves = common_period_curves(backtests, str(a), str(b))
            st.markdown("##### 共同回测区间的净值与回撤")
            if curves.empty:
                st.info("两组实验没有足够的共同回测月份，暂时不能生成公平区间曲线。")
            else:
                net_figure, drawdown_figure = common_period_figures(curves)
                chart_left, chart_right = st.columns(2)
                chart_left.plotly_chart(net_figure, use_container_width=True)
                chart_right.plotly_chart(drawdown_figure, use_container_width=True)

            analysis = comparison_analysis(core_raw, curves)
            st.markdown("##### 选股实验分析与结论")
            st.info(f"{analysis['status']}：{analysis['summary']}")
            for detail in analysis["details"]:
                st.write(f"- {detail}")

            comparison_export = pd.concat([core_raw, config_raw, weight_raw], ignore_index=True, sort=False)
            comparison_export["experiment_a_id"] = str(a)
            comparison_export["experiment_b_id"] = str(b)
            st.download_button(
                "下载两组实验完整对比CSV",
                comparison_export.to_csv(index=False).encode("utf-8-sig"),
                f"experiment_comparison_{a}_{b}.csv",
                "text/csv",
            )
    else:
        st.info("至少保存两组实验后可进行完整对比。")

st.caption("完整实验请优先使用ZIP和SQLite备份留档。仅导入实验汇总CSV不会恢复月度因子、Rank IC、回测或持仓明细，因此不能直接批准为正式实验。")
