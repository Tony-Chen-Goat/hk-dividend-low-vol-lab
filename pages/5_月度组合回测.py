from __future__ import annotations

import pandas as pd
import streamlit as st

from app.backtest import performance_metrics
from app.charts import equity_curve_chart
from app.config import BENCHMARKS, DEFAULT_DB_PATH, RISK_DEFAULTS
from app.database import read_table
from app.research_pipeline import backtest_from_panel, load_feature_panel
from app.ui import empty_state, setup_page


setup_page("月度组合回测", "📈")
panel = load_feature_panel(DEFAULT_DB_PATH)
if panel.empty:
    empty_state("尚无月度因子面板。请先在因子实验室执行计算。")
    st.stop()

controls = st.columns(5)
mode = controls[0].selectbox("模型", ["港股13因子增强模型", "文章方案一基准"])
top_n = controls[1].slider("入选数量", 10, 50, 30)
method_label = controls[2].selectbox("资金配置", ["50%股息率＋50%逆波动率", "股息率加权", "逆波动率加权"], disabled=mode == "文章方案一基准")
cost = controls[3].number_input("单边交易成本", 0.0, 0.02, 0.001, 0.0001, format="%.4f")
max_stock = controls[4].slider("单股上限", 0.01, 0.20, RISK_DEFAULTS["max_stock_weight"], 0.01)
method_map = {"50%股息率＋50%逆波动率": "blend", "股息率加权": "dividend", "逆波动率加权": "inverse_volatility"}
monthly, holdings = backtest_from_panel(panel, "enhanced" if mode.startswith("港股") else "article", top_n, method_map[method_label], cost, {"max_stock_weight": max_stock})
if monthly.empty:
    empty_state("没有足够的下一月收益或完整因子用于回测。")
    st.stop()
prices = read_table("daily_prices", DEFAULT_DB_PATH)
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
st.markdown('<span class="oos-tag">结果需按样本内 / 样本外窗口分别评估</span>', unsafe_allow_html=True)
cols = st.columns(6)
for column, (label, key, fmt) in zip(cols, [
    ("年化收益", "annualized_return", ".1%"), ("年化波动", "annualized_volatility", ".1%"),
    ("夏普", "sharpe", ".2f"), ("最大回撤", "max_drawdown", ".1%"),
    ("Calmar", "calmar", ".2f"), ("月均换手", "average_turnover", ".1%"),
]):
    value = metrics[key]
    column.metric(label, format(value, fmt) if pd.notna(value) else "—")
st.plotly_chart(equity_curve_chart(monthly), use_container_width=True)
tab1, tab2, tab3 = st.tabs(["月度收益与回撤", "每月持仓", "行业分布"])
with tab1:
    st.dataframe(monthly, use_container_width=True, hide_index=True)
with tab2:
    st.dataframe(holdings, use_container_width=True, hide_index=True)
with tab3:
    if "sector" in holdings:
        sector = holdings.groupby(["month_end", "sector"], dropna=False)["target_weight"].sum().reset_index()
        st.dataframe(sector, use_container_width=True, hide_index=True)
st.caption("文章方案一基准：月频调仓、传统日波动率筛选并按股息率加权；不使用 13 因子总分和日频 CV 代理。增强模型结果不得解释为文章原始回测结果。")
