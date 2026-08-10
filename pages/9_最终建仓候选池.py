from __future__ import annotations

import pandas as pd
import streamlit as st

from app.display import localized_csv, localized_frame
from app.final_pool import build_final_candidate_pool
from app.ui import setup_page


setup_page("最终建仓候选池", "✅")
st.write("上传风险过滤入选池与最新因子选股结果，系统将按证券代码取交集，并剔除零权重、因子覆盖不足或组合约束未通过的股票。")
st.warning("本页输出是建仓前人工复核清单，不是自动买入指令。请继续核对港交所公告、成交量、每手股数、实时价格和账户风险。")

upload_cols = st.columns(2)
risk_file = upload_cols[0].file_uploader(
    "① 上传风险过滤入选CSV",
    type=["csv"],
    help="来自“股票池与风险过滤”页面的 included_universe.csv 或中文字段版本。",
)
selection_file = upload_cols[1].file_uploader(
    "② 上传最新因子选股CSV",
    type=["csv"],
    help="来自“最新选股结果”页面的 latest_selection_日期.csv 或中文字段版本。",
)

if risk_file and selection_file:
    try:
        risk = pd.read_csv(risk_file, dtype=str)
        selection = pd.read_csv(selection_file, dtype=str)
        final, excluded = build_final_candidate_pool(risk, selection)
    except Exception as exc:
        st.error(f"CSV校验或交集计算失败：{exc}")
        st.stop()

    metrics = st.columns(4)
    metrics[0].metric("风险合格股票", risk.shape[0])
    metrics[1].metric("因子精选股票", selection.shape[0])
    metrics[2].metric("最终交集股票", final.shape[0])
    metrics[3].metric("未进入最终池", excluded.shape[0])

    if "month_end" in final and final["month_end"].notna().any():
        latest_month = pd.to_datetime(final["month_end"], errors="coerce").max()
        if pd.notna(latest_month):
            st.caption(f"最新因子月末：{latest_month.date().isoformat()}。风险过滤CSV没有固定快照日期字段，请确认两份文件来自同一次数据更新。")
    else:
        st.caption("风险过滤CSV没有固定快照日期字段，请确认两份文件来自同一次数据更新。")

    st.markdown("#### 最终交集与人工复核")
    if final.empty:
        st.warning("两份CSV没有形成符合全部条件的交集，请查看下方未进入最终池原因。")
    else:
        review = localized_frame(final)
        review.insert(0, "批准进入候选池", False)
        review.insert(1, "公告复核状态", "待复核")
        suggested = pd.to_numeric(final.get("target_weight"), errors="coerce").fillna(0).to_numpy()
        review.insert(2, "人工计划权重", suggested)
        review.insert(3, "人工备注", "")
        edited = st.data_editor(
            review,
            use_container_width=True,
            hide_index=True,
            disabled=[column for column in review.columns if column not in {"批准进入候选池", "公告复核状态", "人工计划权重", "人工备注"}],
            column_config={
                "批准进入候选池": st.column_config.CheckboxColumn("批准进入候选池"),
                "公告复核状态": st.column_config.SelectboxColumn("公告复核状态", options=["待复核", "已核对无异常", "发现风险", "不适用"]),
                "人工计划权重": st.column_config.NumberColumn("人工计划权重", min_value=0.0, max_value=1.0, step=0.001, format="percent"),
                "人工备注": st.column_config.TextColumn("人工备注"),
            },
            key="final_pool_review",
        )
        approved = edited[edited["批准进入候选池"]].copy()
        approved_weight = pd.to_numeric(approved["人工计划权重"], errors="coerce").fillna(0).sum()
        st.write(f"已人工批准 **{len(approved)}** 只；人工计划权重合计 **{approved_weight:.1%}**。")
        if approved_weight > 1 + 1e-9:
            st.error("人工计划权重超过100%，请调整后再下载。")
        elif approved.empty:
            st.info("请逐只完成公告复核并勾选“批准进入候选池”；也可以先下载未审批的交集清单。")

        download_cols = st.columns(3)
        download_cols[0].download_button(
            "下载未审批交集CSV",
            localized_csv(final),
            "final_candidate_intersection.csv",
        )
        download_cols[1].download_button(
            "下载人工复核表CSV",
            edited.to_csv(index=False).encode("utf-8-sig"),
            "final_candidate_review.csv",
        )
        download_cols[2].download_button(
            "下载已批准候选池CSV",
            approved.to_csv(index=False).encode("utf-8-sig"),
            "approved_build_candidates.csv",
            disabled=approved.empty or approved_weight > 1 + 1e-9,
        )

    st.markdown("#### 未进入最终池的股票与原因")
    if excluded.empty:
        st.success("没有额外被排除的股票。")
    else:
        preferred = [column for column in ["symbol", "name", "sector", "target_weight", "factor_coverage", "final_exclusion_reasons"] if column in excluded]
        st.dataframe(localized_frame(excluded[preferred]), use_container_width=True, hide_index=True)
else:
    st.info("请先上传两份CSV。标准字段版和中文字段版都可以识别。")

st.markdown("#### 交集规则")
st.write("证券必须同时存在于风险合格池和最新因子精选池，并满足建议目标权重大于0、因子数据覆盖率100%、组合约束状态为“满足约束”。")
