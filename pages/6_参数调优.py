from __future__ import annotations

import pandas as pd
import streamlit as st

from app.backtest import performance_metrics
from app.config import DEFAULT_DB_PATH, FACTOR_GROUPS, FACTOR_WEIGHTS
from app.experiment_store import save_experiment
from app.optimizer import experiment_score, group_weight_candidates, sampled_weight_candidates
from app.rank_ic import ic_summary, monthly_rank_ic
from app.research_pipeline import backtest_from_panel, load_feature_panel
from app.scoring import score_cross_section
from app.ui import empty_state, setup_page


setup_page("参数调优", "🎛️")
panel = load_feature_panel(DEFAULT_DB_PATH)
if panel.empty:
    empty_state("尚无因子面板，无法进行滚动样本外调优。")
    st.stop()

st.markdown("#### 两层有限搜索")
st.write("第一层在红利 30%–50%、低波 30%–50%、质量/流动性/规模 15%–30% 范围内按 5 个百分点搜索；第二层保留组内基准比例。本版本不暴力穷举 13 因子的全部组合。")
cols = st.columns(4)
max_experiments = cols[0].number_input("最大实验数", 1, 200, 25)
top_n = cols[1].slider("入选数量", 10, 50, 30)
transaction_cost = cols[2].number_input("交易成本", 0.0, 0.02, 0.001, 0.0001, format="%.4f")
validation_months = cols[3].number_input("验证期（月）", 6, 36, 12)
candidates = sampled_weight_candidates(int(max_experiments))
st.metric("预计实验数量", len(candidates))
if "cancel_opt" not in st.session_state:
    st.session_state.cancel_opt = False
if st.button("取消当前测试"):
    st.session_state.cancel_opt = True

if st.button("开始样本外参数实验", type="primary"):
    st.session_state.cancel_opt = False
    months = sorted(panel["month_end"].dropna().unique())
    if len(months) < 60 + validation_months:
        st.error(f"至少需要 {60 + validation_months} 个月数据（前5年训练＋验证期）。")
    else:
        validation_set = set(months[-int(validation_months):])
        validation = panel[panel["month_end"].isin(validation_set)].copy()
        bar, status = st.progress(0.0), st.empty()
        best = None
        for index, weights in enumerate(candidates, start=1):
            if st.session_state.cancel_opt:
                st.warning("测试已取消，已完成结果仍保留。")
                break
            rescored = pd.concat([score_cross_section(group, weights) for _, group in validation.groupby("month_end")], ignore_index=True)
            monthly_ic = monthly_rank_ic(rescored, "model_score", "forward_return")
            ic = ic_summary(monthly_ic)
            bt, _ = backtest_from_panel(rescored, "enhanced", top_n, "blend", transaction_cost)
            perf = performance_metrics(bt)
            if pd.isna(ic["rank_icir"]) or pd.isna(perf["information_ratio"]):
                info = 0.0 if pd.isna(perf["information_ratio"]) else perf["information_ratio"]
                icir = 0.0 if pd.isna(ic["rank_icir"]) else ic["rank_icir"]
            else:
                info, icir = perf["information_ratio"], ic["rank_icir"]
            score = experiment_score(icir, info, perf["max_drawdown"], perf["average_turnover"])
            payload = {
                "name": "BASELINE" if index == 1 else f"OOS-{index:03d}", "universe_name": "当前导入证券池",
                "data_start": str(panel["month_end"].min().date()), "data_end": str(panel["month_end"].max().date()),
                "train_window": f"起始至验证期前（至少5年）", "validation_window": f"末{validation_months}个月",
                "factor_weights": weights, "group_weights": {group: sum(weights[f] for f in factors) for group, factors in FACTOR_GROUPS.items()},
                "portfolio_method": "blend", "selected_count": top_n, "transaction_cost": transaction_cost,
                "metrics": {**ic, **perf}, "score": score, "coverage": float(rescored["factor_coverage"].mean()),
                "survivor_bias": True, "quality_note": "仅使用样本外验证期评分；当前成分股回溯时存在幸存者偏差。", "is_out_of_sample": True,
            }
            save_experiment(payload, DEFAULT_DB_PATH)
            if best is None or score > best["score"]:
                best = payload
            bar.progress(index / len(candidates)); status.caption(f"实验 {index}/{len(candidates)} · 当前最佳 {best['name']} · {best['score']:.3f}")
        if best:
            st.success(f"实验完成。当前最佳样本外实验：{best['name']}，得分 {best['score']:.3f}。")

st.markdown("#### 默认实验评分")
st.code("RankICIR + 0.5 × 组合信息比率 - 0.5 × 最大回撤 - 0.2 × 月均换手率", language=None)
st.caption("最大回撤和换手率均使用正数小数。不能反复利用同一验证期调参后宣称结果可以泛化。")
