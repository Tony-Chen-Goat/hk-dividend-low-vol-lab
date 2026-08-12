from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from app.analysis import backtest_analysis
from app.backtest import performance_metrics
from app.charts import equity_curve_chart
from app.config import BENCHMARKS, DEFAULT_DB_PATH, MODEL_LABELS, RISK_DEFAULTS
from app.database import read_table
from app.display import localized_frame
from app.research_pipeline import available_feature_models, backtest_from_panel, load_feature_panel
from app.ui import empty_state, setup_page


setup_page("月度组合回测", "📈")
available_models = available_feature_models(DEFAULT_DB_PATH)
if not available_models:
    empty_state("尚无月度因子面板。请先在因子实验室执行计算。")
    st.stop()
model_name = st.selectbox(
    "因子模式",
    available_models,
    format_func=MODEL_LABELS.get,
)
panel = load_feature_panel(DEFAULT_DB_PATH, model_name)
if panel.empty:
    empty_state("尚无月度因子面板。请先在因子实验室执行计算。")
    st.stop()

st.info("本页执行动态月度调仓：每个月末只使用当时已知的因子综合得分重新排名并选择前N只；Rank IC仅用于验证排名质量，不参与当月选股，也不会使用下一月收益决定持仓。")
controls = st.columns(5)
mode = controls[0].selectbox("组合模型", ["因子增强模型", "文章方案一基准"])
top_n = controls[1].slider("每月入选数量", 3, 15, 10)
backtest_start = controls[2].date_input("回测开始日期", value=date(2016, 1, 1))
cost = controls[3].number_input("单边交易成本", 0.0, 0.02, 0.001, 0.0001, format="%.4f")
max_stock = controls[4].slider("单股上限", 0.01, 0.20, RISK_DEFAULTS["max_stock_weight"], 0.01)

mix_cols = st.columns(2)
dividend_pct = mix_cols[0].number_input("股息率配置比例（%）", 0, 100, 50, 5, disabled=mode == "文章方案一基准")
inverse_vol_pct = mix_cols[1].number_input("逆波动率配置比例（%）", 0, 100, 50, 5, disabled=mode == "文章方案一基准")
if mode == "因子增强模型" and dividend_pct + inverse_vol_pct != 100:
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
        f"按当前每月入选 {top_n} 只、单股上限 {max_stock:.0%}及前5大权重上限 {top5_limit:.0%}，"
        "即使其他约束全部满足，"
        f"股票仓位最多也只有 {maximum_invested:.0%}，至少会保留 {1 - maximum_invested:.0%} 现金。"
    )

prices = read_table("daily_prices", DEFAULT_DB_PATH)
stock_prices = prices[~prices["symbol"].astype(str).str.startswith("^")].copy() if not prices.empty else prices
raw_start = pd.to_datetime(stock_prices["trade_date"], errors="coerce").min() if not stock_prices.empty else pd.NaT
if backtest_start <= date(2016, 1, 1) and (pd.isna(raw_start) or raw_start.date() > date(2011, 1, 31)):
    st.warning("要从2016年开始形成完整10因子月度组合，建议先回到数据中心把原始数据开始日期设为2011-01-01，重新更新Yahoo数据并在因子实验室重新计算。当前系统会从实际具备完整因子和下一月收益的首个月开始。")

settings = {
    "max_stock_weight": max_stock,
    "dividend_mix": float(dividend_pct) / 100,
}
monthly, holdings = backtest_from_panel(
    panel,
    "enhanced" if mode == "因子增强模型" else "article",
    top_n,
    "blend",
    cost,
    settings,
    start_date=backtest_start,
)
if monthly.empty:
    empty_state("没有足够的下一月收益或完整因子用于回测。")
    st.stop()
benchmark_return = None
if not prices.empty:
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    monthly["period"] = pd.to_datetime(monthly["month_end"]).dt.to_period("M")
    for benchmark_name, benchmark_symbol in BENCHMARKS.items():
        bench = prices[prices["symbol"] == benchmark_symbol].sort_values("trade_date").copy()
        if not bench.empty:
            bench = bench.groupby(bench["trade_date"].dt.to_period("M")).tail(1)
            bench["period"] = bench["trade_date"].dt.to_period("M")
            bench["benchmark_return"] = bench["adjusted_close"].pct_change(fill_method=None)
            mapping = bench.set_index("period")["benchmark_return"]
            monthly[f"{benchmark_name}_return"] = monthly["period"].map(mapping)
            monthly[f"{benchmark_name}_value"] = (1 + monthly[f"{benchmark_name}_return"].fillna(0)).cumprod()
            if benchmark_return is None:
                benchmark_return = monthly[f"{benchmark_name}_return"]
metrics = performance_metrics(monthly, benchmark_return)
actual_start = pd.to_datetime(monthly["month_end"]).min()
actual_end = pd.to_datetime(monthly["month_end"]).max()
st.caption(f"实际回测信号区间：{actual_start.date().isoformat()} 至 {actual_end.date().isoformat()}；每月动态选择因子综合得分前 {top_n} 名。")
st.markdown('<span class="oos-tag">结果需按样本内 / 样本外窗口分别评估</span>', unsafe_allow_html=True)
cols = st.columns(6)
for column, (label, key, fmt) in zip(cols, [
    ("年化收益", "annualized_return", ".1%"), ("年化波动", "annualized_volatility", ".1%"),
    ("夏普", "sharpe", ".2f"), ("最大回撤", "max_drawdown", ".1%"),
    ("Calmar", "calmar", ".2f"), ("月均换手", "average_turnover", ".1%"),
]):
    value = metrics[key]
    column.metric(label, format(value, fmt) if pd.notna(value) else "—")
st.markdown("#### 动态月度调仓净值")
st.plotly_chart(equity_curve_chart(monthly[["month_end", "net_value", "gross_value"]]), use_container_width=True)
analysis = backtest_analysis(metrics, monthly, benchmark_return)
st.markdown("#### 通俗分析与研究结论")
st.info(f"{analysis['status']}：{analysis['summary']}")
for detail in analysis["details"]:
    st.write(f"- {detail}")
st.caption("自动结论基于固定的收益、夏普、回撤和换手率分档，不代表实盘收益承诺；需结合样本外结果和幸存者偏差解读。")

tab1, tab2, tab3, tab4 = st.tabs(["月度收益与回撤", "每月调仓进出", "每月持仓", "行业分布"])
with tab1:
    st.dataframe(localized_frame(monthly), use_container_width=True, hide_index=True)
with tab2:
    rebalance_columns = ["month_end", "selected_count", "entered_count", "exited_count", "entered_symbols", "exited_symbols", "retained_symbols", "turnover", "transaction_cost"]
    st.dataframe(localized_frame(monthly[[column for column in rebalance_columns if column in monthly]]), use_container_width=True, hide_index=True)
with tab3:
    st.dataframe(localized_frame(holdings), use_container_width=True, hide_index=True)
with tab4:
    if "sector" in holdings:
        sector = holdings.groupby(["month_end", "sector"], dropna=False)["target_weight"].sum().reset_index()
        st.dataframe(localized_frame(sector), use_container_width=True, hide_index=True)
st.caption("gross_value为未扣交易成本的动态月度调仓累计净值；net_value为扣除交易成本后的累计净值。文章方案一基准：月频调仓、传统日波动率筛选并按股息率加权；不使用因子总分和日频CV代理。")
