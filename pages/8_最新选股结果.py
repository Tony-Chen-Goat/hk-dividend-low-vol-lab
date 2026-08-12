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
controls = st.columns(3)
top_n = controls[0].slider("入选数量", 3, 15, 10)
max_stock = controls[1].slider("单股上限", 0.01, 0.20, RISK_DEFAULTS["max_stock_weight"], 0.01)
max_sector = controls[2].slider("单行业上限", 0.05, 0.60, RISK_DEFAULTS["max_sector_weight"], 0.05)
st.markdown("#### 资金配置")
mix_cols = st.columns(2)
dividend_pct = mix_cols[0].number_input("股息率配置比例（%）", 0, 100, 50, 5)
inverse_vol_pct = mix_cols[1].number_input("逆波动率配置比例（%）", 0, 100, 50, 5)
if dividend_pct + inverse_vol_pct != 100:
    st.error(f"两项资金配置比例必须合计100%，当前为 {dividend_pct + inverse_vol_pct}%。")
    st.stop()
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
st.caption("因子评分权重与资金配置权重相互独立。缺失数据不会被填成可通过筛选的默认值；约束无法满足时保留现金。")
