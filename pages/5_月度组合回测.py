from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from app.analysis import backtest_analysis
from app.backtest import performance_metrics
from app.benchmarks import add_benchmark_curves
from app.config import BENCHMARKS, DEFAULT_DB_PATH, MODEL_LABELS, RISK_DEFAULTS
from app.database import load_setting, minimum_stock_trade_date, read_table
from app.display import localized_frame
from app.experiment_store import experiment_display_name, experiment_score, get_experiment, store_backtest_results
from app.monthly_details import monthly_rebalance_details
from app.monthly_chart import (
    available_chart_months,
    chart_input_window,
    equity_curve_chart,
    filter_chart_window,
    selected_month_from_chart_event,
)
from app.research_pipeline import available_experiments, backtest_from_panel, load_feature_panel
from app.ui import empty_state, setup_page


setup_page("月度组合回测", "📈")
saved_notice = st.session_state.pop("backtest_saved_notice", None)
if saved_notice:
    st.success(saved_notice)


@st.dialog("月度调仓详情", width="large")
def show_monthly_rebalance_dialog(selected_month, monthly_data: pd.DataFrame, holdings_data: pd.DataFrame):
    summary, transactions, positions = monthly_rebalance_details(
        monthly_data, holdings_data, selected_month
    )
    if summary is None:
        st.warning("找不到该月份的回测记录。")
        return

    month_label = pd.Timestamp(selected_month).strftime("%Y年%m月")
    st.subheader(month_label)
    st.caption("这是该月月末形成的调仓信号与持仓；持仓收益在下一月实现。")
    metric_columns = st.columns(4)
    metric_columns[0].metric("扣费后组合收益", f"{float(summary.get('net_return', 0)):.2%}")
    metric_columns[1].metric("组合换手率", f"{float(summary.get('turnover', 0)):.2%}")
    metric_columns[2].metric("交易成本", f"{float(summary.get('transaction_cost', 0)):.3%}")
    metric_columns[3].metric("保留现金比例", f"{float(summary.get('cash_weight', 0)):.2%}")

    transaction_tab, holding_tab = st.tabs(["每月交易记录", "每月持仓情况"])
    with transaction_tab:
        st.dataframe(transactions, use_container_width=True, hide_index=True)
    with holding_tab:
        if positions.empty:
            st.info("该月份没有可展示的实际持仓。")
        else:
            holding_columns = [
                "symbol", "name", "sector", "model_score", "target_weight",
                "forward_return", "contribution", "rebalance_action",
            ]
            st.dataframe(
                localized_frame(positions[[column for column in holding_columns if column in positions]]),
                use_container_width=True,
                hide_index=True,
            )


experiments = available_experiments(DEFAULT_DB_PATH)
if experiments.empty:
    empty_state("尚无月度因子面板。请先在因子实验室执行计算。")
    st.stop()
experiment_options = experiments["experiment_id"].astype(str).tolist()
preferred = st.session_state.get("active_experiment_id")
index = experiment_options.index(preferred) if preferred in experiment_options else 0
experiment_id = st.selectbox(
    "选择实验版本",
    experiment_options,
    index=index,
    format_func=lambda value: f"{experiment_display_name(experiments.set_index('experiment_id').loc[value])} · {MODEL_LABELS.get(experiments.set_index('experiment_id').loc[value, 'model_name'], experiments.set_index('experiment_id').loc[value, 'model_name'])} · {value}",
)
st.session_state["active_experiment_id"] = experiment_id
experiment = get_experiment(experiment_id, DEFAULT_DB_PATH)
benchmark_state = load_setting("benchmark_data_update_state", {}, DEFAULT_DB_PATH) or {}
benchmark_revision = int(benchmark_state.get("revision", 0) or 0)
model_name = experiment["model_name"]
panel = load_feature_panel(DEFAULT_DB_PATH, model_name, experiment_id)
if panel.empty:
    empty_state("尚无月度因子面板。请先在因子实验室执行计算。")
    st.stop()

st.info("本页执行动态月度调仓：每个月末只使用当时已知的因子综合得分重新排名并选择前N只；Rank IC仅用于验证排名质量，不参与当月选股，也不会使用下一月收益决定持仓。")
locked = bool(experiment.get("approved"))
saved_backtest = experiment.get("backtest_settings") or {}
if locked:
    st.success("这是已经批准的正式实验。回测设置已锁定；如需调整，请回到因子实验室创建新的实验版本。")
if "rank_icir" not in (experiment.get("metrics") or {}):
    st.warning("该实验尚未完成Rank IC测试。建议先到“Rank IC测试”选择同一实验编号；当前仍可回测，但实验综合比较将缺少Rank IC依据。")
controls = st.columns(5)
mode_options = ["因子增强模型", "文章方案一基准"]
saved_mode = "文章方案一基准" if saved_backtest.get("portfolio_method") == "article" else "因子增强模型"
mode = controls[0].selectbox("组合模型", mode_options, index=mode_options.index(saved_mode), disabled=locked)
top_n = controls[1].slider("每月入选数量", 3, 15, int(saved_backtest.get("selected_count", 10)), disabled=locked)
saved_start = pd.to_datetime(saved_backtest.get("backtest_start"), errors="coerce")
backtest_start = controls[2].date_input("回测开始日期", value=saved_start.date() if pd.notna(saved_start) else date(2016, 1, 1), disabled=locked)
cost = controls[3].number_input("单边交易成本", 0.0, 0.02, float(saved_backtest.get("transaction_cost", 0.001)), 0.0001, format="%.4f", disabled=locked)
max_stock = controls[4].slider("单股上限", 0.01, 0.20, float(saved_backtest.get("max_stock_weight", RISK_DEFAULTS["max_stock_weight"])), 0.01, disabled=locked)

mix_cols = st.columns(2)
dividend_pct = mix_cols[0].number_input("股息率配置比例（%）", 0, 100, int(saved_backtest.get("dividend_pct", 50)), 5, disabled=locked or mode == "文章方案一基准")
inverse_vol_pct = mix_cols[1].number_input("逆波动率配置比例（%）", 0, 100, int(saved_backtest.get("inverse_volatility_pct", 50)), 5, disabled=locked or mode == "文章方案一基准")
if mode == "因子增强模型" and dividend_pct + inverse_vol_pct != 100:
    st.error(f"两项资金配置比例必须合计100%，当前为 {dividend_pct + inverse_vol_pct}%。")
    st.stop()
run_backtest = st.button(
    "运行并保存月度组合回测",
    type="primary",
    disabled=locked,
    help="控件变化只是候选设置；只有点击本按钮才会重算并写入当前实验档案。",
)
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

prices = read_table(
    "daily_prices", DEFAULT_DB_PATH,
    filters={"symbol": list(BENCHMARKS.values())},
    columns=["symbol", "trade_date", "adjusted_close", "close"],
)
raw_start = pd.to_datetime(minimum_stock_trade_date(DEFAULT_DB_PATH), errors="coerce")
if backtest_start <= date(2016, 1, 1) and (pd.isna(raw_start) or raw_start.date() > date(2011, 1, 31)):
    st.warning("要从2016年开始形成完整10因子月度组合，建议先回到数据中心把原始数据开始日期设为2011-01-01，重新更新Yahoo数据并在因子实验室重新计算。当前系统会从实际具备完整因子和下一月收益的首个月开始。")

settings = {
    "max_stock_weight": max_stock,
    "dividend_mix": float(dividend_pct) / 100,
}
candidate_backtest_settings = {
    "backtest_start": str(backtest_start),
    "selected_count": int(top_n),
    "portfolio_method": "blend" if mode == "因子增强模型" else "article",
    "dividend_pct": int(dividend_pct),
    "inverse_volatility_pct": int(inverse_vol_pct),
    "max_stock_weight": float(max_stock),
    "max_sector_weight": float(RISK_DEFAULTS["max_sector_weight"]),
    "transaction_cost": float(cost),
    "benchmark_data_revision": benchmark_revision,
}
if run_backtest:
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
    monthly_with_benchmarks, benchmark_return = add_benchmark_curves(monthly, prices, BENCHMARKS)
    metrics = performance_metrics(monthly_with_benchmarks, benchmark_return)
    rank_icir = experiment.get("metrics", {}).get("rank_icir")
    information_ratio = metrics.get("information_ratio")
    score = experiment_score(
        0.0 if pd.isna(rank_icir) else float(rank_icir),
        0.0 if pd.isna(information_ratio) else float(information_ratio),
        metrics.get("max_drawdown", 0.0),
        metrics.get("average_turnover", 0.0),
    )
    store_backtest_results(
        experiment_id,
        monthly,
        holdings,
        metrics,
        candidate_backtest_settings,
        score,
        DEFAULT_DB_PATH,
    )
    st.session_state["backtest_saved_notice"] = f"实验 {experiment_id} 的月度组合回测已重新计算并保存。"
    st.rerun()

monthly = read_table(
    "backtest_monthly", DEFAULT_DB_PATH,
    filters={"experiment_id": experiment_id},
)
holdings = read_table(
    "backtest_holdings", DEFAULT_DB_PATH,
    filters={"experiment_id": experiment_id},
)
if monthly.empty:
    st.info("该实验尚未保存月度组合回测。请确认上方候选参数后，点击“运行并保存月度组合回测”。")
    st.stop()
monthly["month_end"] = pd.to_datetime(monthly["month_end"], errors="coerce")
holdings["month_end"] = pd.to_datetime(holdings["month_end"], errors="coerce")
if "actual_return" in holdings and "forward_return" not in holdings:
    holdings = holdings.rename(columns={"actual_return": "forward_return"})
monthly, benchmark_return = add_benchmark_curves(monthly, prices, BENCHMARKS)
saved_benchmark_revision = int(saved_backtest.get("benchmark_data_revision", 0) or 0)
st.caption(f"当前基准指数数据修订版：B{benchmark_revision}。")
if saved_backtest and saved_benchmark_revision != benchmark_revision:
    st.warning(
        f"组合持仓仍读取实验归档，但当前基准曲线已从B{saved_benchmark_revision}更新为B{benchmark_revision}。"
        "若要让比较指标绑定新基准版本，请确认后重新运行并保存回测。"
    )
missing_benchmarks = [
    benchmark_name for benchmark_name in BENCHMARKS
    if f"{benchmark_name}_value" not in monthly
    or monthly[f"{benchmark_name}_value"].notna().sum() == 0
]
if missing_benchmarks:
    st.warning(
        f"暂时无法绘制{'、'.join(missing_benchmarks)}：数据库中没有与回测月份连续对齐的指数价格。"
        "请返回数据中心执行“更新已验证基准指数”。"
    )
metrics = performance_metrics(monthly, benchmark_return)
actual_start = pd.to_datetime(monthly["month_end"]).min()
actual_end = pd.to_datetime(monthly["month_end"]).max()
archived_top_n = int(saved_backtest.get("selected_count", experiment.get("selected_count") or top_n))
save_note = "正式实验只读展示" if locked else "下方读取已保存结果；修改控件不会覆盖，须点击运行并保存"
st.caption(f"实验编号：{experiment_id}。实际回测信号区间：{actual_start.date().isoformat()} 至 {actual_end.date().isoformat()}；已保存设置为每月动态选择因子综合得分前 {archived_top_n} 名。{save_note}。")
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
month_options = available_chart_months(monthly)
if not month_options:
    st.warning("已保存回测中没有可识别的真实月份，暂时无法绘制净值曲线。请重新运行并保存月度组合回测。")
    st.stop()
range_preset = st.selectbox(
    "快捷显示范围",
    ["默认近10年", "近5年", "近3年", "全部真实数据", "自选时间段"],
    help="快捷范围只设置起止年月的初始值；右侧仍可继续自选。",
)
years_by_preset = {
    "默认近10年": 10,
    "近5年": 5,
    "近3年": 3,
    "全部真实数据": None,
    "自选时间段": 10,
}
suggested_start, suggested_end = chart_input_window(
    monthly,
    years=years_by_preset[range_preset],
)
suggested_start_period = pd.Period(suggested_start, freq="M")
suggested_end_period = pd.Period(suggested_end, freq="M")
start_group, end_group = st.columns(2)
start_group.markdown("**起始年月**")
start_year_column, start_month_column = start_group.columns(2)
start_year = int(start_year_column.number_input(
    "起始年",
    min_value=2016,
    max_value=int(suggested_end_period.year),
    value=int(suggested_start_period.year),
    step=1,
    key=f"chart_start_year_{experiment_id}_{range_preset}",
))
start_month_number = int(start_month_column.number_input(
    "起始月",
    min_value=1,
    max_value=12,
    value=int(suggested_start_period.month),
    step=1,
    key=f"chart_start_month_number_{experiment_id}_{range_preset}",
))
end_group.markdown("**终止年月**")
end_year_column, end_month_column = end_group.columns(2)
end_year = int(end_year_column.number_input(
    "终止年",
    min_value=2016,
    max_value=int(suggested_end_period.year),
    value=int(suggested_end_period.year),
    step=1,
    key=f"chart_end_year_{experiment_id}_{range_preset}",
))
end_month_number = int(end_month_column.number_input(
    "终止月",
    min_value=1,
    max_value=12,
    value=int(suggested_end_period.month),
    step=1,
    key=f"chart_end_month_number_{experiment_id}_{range_preset}",
))
start_month = f"{start_year:04d}-{start_month_number:02d}"
end_month = f"{end_year:04d}-{end_month_number:02d}"
start_period = pd.Period(start_month, freq="M")
end_period = pd.Period(end_month, freq="M")
if start_period < pd.Period("2016-01", freq="M"):
    st.error("起始年月不能早于2016年1月。")
    chart_monthly = monthly.iloc[0:0].copy()
elif end_period > suggested_end_period:
    st.error(f"终止年月不能晚于最新真实数据月份 {suggested_end_period.strftime('%Y年%m月')}。")
    chart_monthly = monthly.iloc[0:0].copy()
elif start_period > end_period:
    st.error("起始年月不能晚于终止年月，请重新选择。")
    chart_monthly = monthly.iloc[0:0].copy()
else:
    chart_monthly = filter_chart_window(monthly, start_month, end_month)

curve_columns = [
    "month_end", "net_value", "gross_value",
    *[f"{benchmark_name}_value" for benchmark_name in BENCHMARKS],
]
if chart_monthly.empty:
    st.info("所选年月范围内没有真实回测数据。")
else:
    actual_chart_start = pd.to_datetime(chart_monthly["month_end"]).min().strftime("%Y年%m月")
    actual_chart_end = pd.to_datetime(chart_monthly["month_end"]).max().strftime("%Y年%m月")
    st.caption(f"当前图表区间：{actual_chart_start} 至 {actual_chart_end}，共 {len(chart_monthly)} 个真实月度观测。累计净值保持原回测基准，不因截取区间而重新归一化。")
    chart_event = st.plotly_chart(
        equity_curve_chart(chart_monthly[[column for column in curve_columns if column in chart_monthly]]),
        use_container_width=True,
        key=f"monthly_equity_curve_{experiment_id}_{start_month}_{end_month}",
        on_select="rerun",
        selection_mode="points",
    )
    st.caption("横轴按年显示，短刻度代表月份。点击扣费后组合净值曲线上的绿色圆点，可查看该月交易记录与持仓情况。基准指数缺失月份保持为空，不按零收益补齐。")
    selected_month = selected_month_from_chart_event(chart_event)
    if selected_month is not None:
        show_monthly_rebalance_dialog(selected_month, monthly, holdings)
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
st.caption("扣费前组合净值为尚未扣除交易成本的动态月度调仓累计净值；扣费后组合净值为扣除交易成本后的累计净值。文章方案一基准：月频调仓、传统日波动率筛选并按股息率加权；不使用因子总分和日频CV代理。")
