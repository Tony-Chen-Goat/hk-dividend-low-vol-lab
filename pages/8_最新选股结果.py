from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import DEFAULT_DB_PATH, MODEL_FACTOR_WEIGHTS, MODEL_LABELS, RISK_DEFAULTS
from app.display import localized_csv, localized_frame
from app.portfolio import build_enhanced_portfolio
from app.research_pipeline import available_feature_models, load_feature_panel
from app.ui import empty_state, setup_page


setup_page("最新选股结果", "🔎")
available_models = available_feature_models(DEFAULT_DB_PATH)
if not available_models:
    empty_state("尚无真实因子结果。请先更新数据并在因子实验室计算。")
    st.stop()
model_name = st.selectbox(
    "因子模式",
    available_models,
    format_func=MODEL_LABELS.get,
)
panel = load_feature_panel(DEFAULT_DB_PATH, model_name)
if panel.empty:
    empty_state("尚无真实因子结果。请先更新数据并在因子实验室计算。")
    st.stop()
latest_month = panel["month_end"].max()
latest = panel[panel["month_end"] == latest_month].copy()
controls = st.columns(4)
top_n = controls[0].slider("入选数量", 10, 50, 30)
method_label = controls[1].selectbox("资金配置", ["50%股息率＋50%逆波动率", "股息率加权", "逆波动率加权"])
max_stock = controls[2].slider("单股上限", 0.01, 0.20, RISK_DEFAULTS["max_stock_weight"], 0.01)
max_sector = controls[3].slider("单行业上限", 0.05, 0.60, RISK_DEFAULTS["max_sector_weight"], 0.05)
method = {"50%股息率＋50%逆波动率": "blend", "股息率加权": "dividend", "逆波动率加权": "inverse_volatility"}[method_label]
portfolio = build_enhanced_portfolio(latest, top_n, method, {"max_stock_weight": max_stock, "max_sector_weight": max_sector})
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
st.caption("因子评分权重与资金配置权重相互独立。缺失数据不会被填成可通过筛选的默认值；约束无法满足时保留现金。")
