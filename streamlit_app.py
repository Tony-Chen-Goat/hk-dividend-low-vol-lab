from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import DEFAULT_DB_PATH
from app.database import read_table, table_counts
from app.experiment_store import list_experiments
from app.ui import cloud_storage_notice, empty_state, setup_page, yahoo_notice


quality = setup_page("港股红利低波实验室", "🧭")
counts = table_counts(DEFAULT_DB_PATH)
experiments = list_experiments(DEFAULT_DB_PATH)
features = read_table("monthly_features", DEFAULT_DB_PATH)

st.markdown("#### 以时间序列纪律为核心的港股红利低波研究工作台")
st.write("按月末先执行风险过滤，再计算红利、低波、质量、流动性与规模因子，并使用下一月收益进行 Rank IC 与组合验证。每次手动权重实验通过独立编号保存，完成比较并批准一套正式实验后生成最新选股与人工复核清单。")

c1, c2, c3, c4 = st.columns(4)
c1.metric("证券池", f"{counts['security_master']:,}")
c2.metric("日线记录", f"{counts['daily_prices']:,}")
c3.metric("分红记录", f"{counts['dividends']:,}")
latest_count = 0
if not features.empty:
    latest = features["month_end"].max()
    latest_count = int(features.loc[features["month_end"] == latest, "symbol"].nunique())
c4.metric("最新选股候选", f"{latest_count:,}")

left, right = st.columns([1.35, 1])
with left:
    st.markdown("#### 当前最佳样本外实验")
    if experiments.empty:
        empty_state("尚未保存完整实验。请在因子实验室创建实验，再完成Rank IC和月度组合回测。")
    else:
        best = experiments[experiments["status"] == "completed"].head(1)
        if best.empty:
            empty_state("当前实验尚未完成月度组合回测。")
        else:
            row = best.iloc[0]
            st.markdown('<span class="oos-tag">历史研究表现</span>', unsafe_allow_html=True)
            st.subheader(row["name"])
            a, b, c = st.columns(3)
            a.metric("综合得分", f"{row['score']:.3f}" if pd.notna(row["score"]) else "—")
            b.metric("Rank ICIR", f"{row.get('rank_icir', float('nan')):.2f}" if pd.notna(row.get("rank_icir")) else "—")
            c.metric("最大回撤", f"{row.get('max_drawdown', float('nan')):.1%}" if pd.notna(row.get("max_drawdown")) else "—")
with right:
    st.markdown("#### 数据质量摘要")
    st.write(f"价格覆盖：{quality['price_coverage']:.1%}")
    st.write(f"分红覆盖：{quality['dividend_coverage']:.1%}")
    st.write(f"财务覆盖：{quality['fundamental_coverage']:.1%}")
    st.write(f"历史成分覆盖：{quality['historical_membership_coverage']:.1%}")
    if quality["disabled_factors"]:
        st.warning("完整13因子因数据缺失而禁用：" + "、".join(quality["disabled_factors"]) + "；Yahoo 基础10因子仍可运行。")

st.markdown("#### 研究边界与风险")
st.markdown('<div class="warning-box">本工具用于研究，不构成投资建议。yfinance 是非官方数据接口；指数历史成分、财务公告日期、自由流通股本与退市事件覆盖不足时，结果可能含幸存者偏差或无法计算。任何增强模型结果都不是参考文章的原始回测结果。</div>', unsafe_allow_html=True)
yahoo_notice()
cloud_storage_notice()
