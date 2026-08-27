from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import DEFAULT_DB_PATH, MODEL_FACTOR_WEIGHTS, MODEL_LABELS, RISK_DEFAULTS
from app.display import localized_csv, localized_frame
from app.entry_points import calculate_entry_references
from app.experiment_store import get_experiment, list_experiments
from app.portfolio import build_enhanced_portfolio
from app.research_pipeline import load_feature_panel
from app.stability import read_recent_stock_prices, resolve_stock_data_cutoff
from app.ui import empty_state, setup_page


ENTRY_LABELS = {
    "signal_as_of": "信号数据日",
    "latest_price": "最新收盘价（港元）",
    "ma5": "5日均线（港元）",
    "ma20": "20日均线（港元）",
    "return_20d": "近20日涨跌幅",
    "trend_strength": "趋势强弱",
    "reference_ma": "参考均线",
    "reference_price": "参考买点（港元）",
    "reference_low": "观察区间下限（港元）",
    "reference_high": "观察区间上限（港元）",
    "price_vs_reference": "现价相对参考线",
    "entry_guidance": "买点参考说明",
    "price_data_points": "有效价格样本数",
}


def _stable_html_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<div class="stable-table-empty">暂无可显示记录</div>'
    table = frame.to_html(index=False, escape=True, border=0, classes="stable-table", na_rep="—")
    return f'<div class="stable-table-wrap">{table}</div>'


setup_page("最新选股结果", "🔎")
experiments = list_experiments(DEFAULT_DB_PATH)
approved = experiments[experiments["approved"] == 1] if not experiments.empty and "approved" in experiments else pd.DataFrame()
if approved.empty:
    empty_state("尚未批准正式实验。请先完成一轮因子实验、Rank IC和月度组合回测，然后在“实验档案与对比”批准一套实验。")
    st.stop()
experiment_id = str(approved.iloc[0]["experiment_id"])
experiment = get_experiment(experiment_id, DEFAULT_DB_PATH)
model_name = experiment["model_name"]
panel = load_feature_panel(DEFAULT_DB_PATH, model_name, experiment_id, latest_only=True)
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
st.success(f"正式实验：{experiment['display_name']} · {experiment_id} · {MODEL_LABELS.get(model_name, model_name)}")
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
entry_symbols = portfolio.loc[portfolio["target_weight"] > 0, "symbol"].head(10).astype(str).tolist()
entry_prices = pd.DataFrame()
if entry_symbols:
    entry_cutoff = resolve_stock_data_cutoff(DEFAULT_DB_PATH, entry_symbols).get("as_of")
    entry_prices = read_recent_stock_prices(
        DEFAULT_DB_PATH, 60, symbols=entry_symbols, as_of=entry_cutoff,
    )
entry_references = calculate_entry_references(portfolio, entry_prices, limit=10)
if not entry_references.empty:
    reference_columns = [column for column in entry_references if column != "symbol"]
    reference_lookup = entry_references.set_index("symbol")
    for column in reference_columns:
        portfolio[column] = portfolio["symbol"].astype(str).map(reference_lookup[column])
st.markdown(f'<span class="oos-tag">因子月末 {latest_month.date().isoformat()}</span>', unsafe_allow_html=True)
cols = st.columns(4)
cols[0].metric("候选股票", len(latest))
cols[1].metric("最终入选", int((portfolio["target_weight"] > 0).sum()))
cols[2].metric("股票权重", f"{portfolio['target_weight'].sum():.1%}")
cols[3].metric("保留现金", f"{portfolio['cash_weight'].sum():.1%}")
display = ["排名", "symbol", "name", "sector", "model_score", "factor_coverage", "target_weight", "constraint_note"] + [factor for factor in MODEL_FACTOR_WEIGHTS[model_name] if factor in portfolio]
localized = localized_frame(portfolio[display])
st.dataframe(localized, use_container_width=True, hide_index=True, column_config={"建议目标权重": st.column_config.ProgressColumn("建议目标权重", format="percent", min_value=0, max_value=max_stock), "因子数据覆盖率": st.column_config.ProgressColumn("因子数据覆盖率", format="percent", min_value=0, max_value=1)})
st.markdown("#### 前10只入选股票的均线买点参考")
st.info("固定研究规则：5日均线高于20日均线且近20日收益为正时，按短线趋势较强处理并参考5日线；其他情况参考20日线。观察区间为参考均线上下1%。这是一项技术面辅助信息，不是收益预测或自动买入指令。")
if entry_references.empty:
    st.warning("当前入选股票缺少足够的近期价格数据，暂时无法生成均线买点参考。")
else:
    entry_display = portfolio.loc[
        portfolio["symbol"].astype(str).isin(entry_symbols),
        [
            "排名", "symbol", "name", "signal_as_of", "latest_price", "ma5", "ma20",
            "return_20d", "trend_strength", "reference_ma", "reference_price",
            "reference_low", "reference_high", "price_vs_reference", "entry_guidance",
        ],
    ].copy()
    for column in ["latest_price", "ma5", "ma20", "reference_price", "reference_low", "reference_high"]:
        entry_display[column] = pd.to_numeric(entry_display[column], errors="coerce").round(3)
    for column in ["return_20d", "price_vs_reference"]:
        entry_display[column] = pd.to_numeric(entry_display[column], errors="coerce").map(
            lambda value: f"{value:.1%}" if pd.notna(value) else "—"
        )
    entry_display["signal_as_of"] = pd.to_datetime(entry_display["signal_as_of"], errors="coerce").dt.date
    entry_display = localized_frame(entry_display).rename(columns=ENTRY_LABELS)
    st.markdown(_stable_html_table(entry_display), unsafe_allow_html=True)
download_cols = st.columns(2)
download_cols[0].download_button("下载标准字段CSV", portfolio.to_csv(index=False).encode("utf-8-sig"), f"latest_selection_{latest_month.date()}.csv")
download_cols[1].download_button("下载中文字段CSV", localized_csv(portfolio.rename(columns=ENTRY_LABELS)), f"latest_selection_{latest_month.date()}_cn.csv")
st.markdown("#### 人工复核与建仓留档")
st.write("当前名单已经通过该实验的风险过滤，不需要再上传另一份CSV取交集。正式建仓前仍应人工复核最新公告、盈利预警、供股配股、私有化、停牌、派息可持续性和实际成交能力。")
review = portfolio[[column for column in ["symbol", "name", "sector", "model_score", "target_weight", "reference_ma", "reference_price", "entry_guidance"] if column in portfolio]].copy()
review["announcement_review_status"] = "待复核"
review["approved_for_build"] = False
review["manual_target_weight"] = review.get("target_weight", 0.0)
review["manual_note"] = ""
review = st.data_editor(localized_frame(review).rename(columns=ENTRY_LABELS), use_container_width=True, hide_index=True)
st.download_button("下载人工复核建仓清单", review.to_csv(index=False).encode("utf-8-sig"), f"build_review_{experiment_id}_{latest_month.date()}.csv")
st.caption("因子评分权重与资金配置权重相互独立。历史回测表现不是预估收益；缺失数据不会被填成可通过筛选的默认值，约束无法满足时保留现金。")
