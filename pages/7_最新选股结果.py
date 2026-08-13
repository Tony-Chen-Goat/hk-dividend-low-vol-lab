from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import DEFAULT_DB_PATH, MODEL_FACTOR_WEIGHTS, MODEL_LABELS, RISK_DEFAULTS
from app.display import localized_csv, localized_frame
from app.experiment_store import get_experiment, list_experiments
from app.portfolio import build_enhanced_portfolio
from app.research_pipeline import load_feature_panel
from app.ui import empty_state, setup_page


setup_page("最新选股结果", "🔎")
experiments = list_experiments(DEFAULT_DB_PATH)
approved = experiments[experiments["approved"] == 1] if not experiments.empty and "approved" in experiments else pd.DataFrame()
if approved.empty:
    empty_state("尚未批准正式实验。请先完成一轮因子实验、Rank IC和月度组合回测，然后在“实验档案与对比”批准一套实验。")
    st.stop()
experiment_id = str(approved.iloc[0]["experiment_id"])
experiment = get_experiment(experiment_id, DEFAULT_DB_PATH)
model_name = experiment["model_name"]
panel = load_feature_panel(DEFAULT_DB_PATH, model_name, experiment_id)
if panel.empty:
    empty_state("尚无真实因子结果。请先更新数据并在因子实验室计算。")
    st.stop()
latest_month = panel["month_end"].max()
latest = panel[panel["month_end"] == latest_month].copy()
backtest_settings = experiment.get("backtest_settings") or {}
top_n = int(backtest_settings.get("selected_count") or experiment.get("selected_count") or 10)
max_stock = float(backtest_settings.get("max_stock_weight") or experiment.get("max_stock_weight") or RISK_DEFAULTS["max_stock_weight"])
max_sector = float(backtest_settings.get("max_sector_weight") or experiment.get("max_sector_weight") or RISK_DEFAULTS["max_sector_weight"])
dividend_pct = int(backtest_settings.get("dividend_pct", 50))
inverse_vol_pct = int(backtest_settings.get("inverse_volatility_pct", 50))
st.success(f"正式实验：{experiment['name']} · {experiment_id} · {MODEL_LABELS.get(model_name, model_name)}")
st.caption(f"本页只读取已批准实验被冻结设置：每月入选 {top_n} 只，股息率/逆波动率资金配置 {dividend_pct}%/{inverse_vol_pct}%。若要修改，请创建新实验并重新验证后再批准。")
top5_limit = RISK_DEFAULTS["max_top5_weight"]
maximum_invested = min(
    1.0,
    top_n * max_stock,
    top5_limit if top_n <= 5 else top5_limit + (top_n - 5) * max_stock,
)
if maximum_invested < 1:
    st.warning(
        f"按当前入选 {top_n} 只、单股上限 {max_stock:.0%}及前5大权重上限 {top5_limit:.0%}，"
        "即使其他约束全部满足，"
        f"股票仓位最多也只有 {maximum_invested:.0%}，至少会保留 {1 - maximum_invested:.0%} 现金。"
    )
portfolio = build_enhanced_portfolio(
    latest,
    top_n,
    "blend",
    {
        "max_stock_weight": max_stock,
        "max_sector_weight": max_sector,
        "dividend_mix": float(dividend_pct) / 100,
    },
)
portfolio = portfolio.sort_values("model_score", ascending=False).reset_index(drop=True)
portfolio.insert(0, "排名", range(1, len(portfolio) + 1))
st.markdown(f'<span class="oos-tag">因子月末 {latest_month.date().isoformat()}</span>', unsafe_allow_html=True)
cols = st.columns(4)
cols[0].metric("候选股票", len(latest))
cols[1].metric("最终入选", int((portfolio["target_weight"] > 0).sum()))
cols[2].metric("股票权重", f"{portfolio['target_weight'].sum():.1%}")
cols[3].metric("保留现金", f"{portfolio['cash_weight'].sum():.1%}")
display = ["排名", "symbol", "name", "sector", "model_score", "factor_coverage", "target_weight", "constraint_note"] + [factor for factor in MODEL_FACTOR_WEIGHTS[model_name] if factor in portfolio]
localized = localized_frame(portfolio[display])
st.dataframe(localized, use_container_width=True, hide_index=True, column_config={"建议目标权重": st.column_config.ProgressColumn("建议目标权重", format="percent", min_value=0, max_value=max_stock), "因子数据覆盖率": st.column_config.ProgressColumn("因子数据覆盖率", format="percent", min_value=0, max_value=1)})
download_cols = st.columns(2)
download_cols[0].download_button("下载标准字段CSV", portfolio.to_csv(index=False).encode("utf-8-sig"), f"latest_selection_{latest_month.date()}.csv")
download_cols[1].download_button("下载中文字段CSV", localized_csv(portfolio), f"latest_selection_{latest_month.date()}_cn.csv")
st.markdown("#### 人工复核与建仓留档")
st.write("当前名单已经通过该实验的风险过滤，不需要再上传另一份CSV取交集。正式建仓前仍应人工复核最新公告、盈利预警、供股配股、私有化、停牌、派息可持续性和实际成交能力。")
review = portfolio[[column for column in ["symbol", "name", "sector", "model_score", "target_weight"] if column in portfolio]].copy()
review["announcement_review_status"] = "待复核"
review["approved_for_build"] = False
review["manual_target_weight"] = review.get("target_weight", 0.0)
review["manual_note"] = ""
review = st.data_editor(localized_frame(review), use_container_width=True, hide_index=True)
st.download_button("下载人工复核建仓清单", review.to_csv(index=False).encode("utf-8-sig"), f"build_review_{experiment_id}_{latest_month.date()}.csv")
st.caption("因子评分权重与资金配置权重相互独立。历史回测表现不是预估收益；缺失数据不会被填成可通过筛选的默认值，约束无法满足时保留现金。")
