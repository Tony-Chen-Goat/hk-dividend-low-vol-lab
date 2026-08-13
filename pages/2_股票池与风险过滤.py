from __future__ import annotations

import streamlit as st

from app.config import DEFAULT_DB_PATH, MODEL_FULL_13, MODEL_LABELS, MODEL_YAHOO_10, RISK_DEFAULTS
from app.database import load_setting, read_recent_stock_prices, read_table, save_setting
from app.display import localized_csv, localized_frame
from app.ui import empty_state, setup_page
from app.universe import apply_hk_risk_filters, build_risk_snapshot, default_filter_settings


setup_page("股票池与风险过滤", "🧹")
securities = read_table("security_master", DEFAULT_DB_PATH)
prices = read_recent_stock_prices(DEFAULT_DB_PATH, 60)
fundamentals = read_table("fundamentals", DEFAULT_DB_PATH)
if securities.empty or prices.empty:
    empty_state()
    st.stop()

st.markdown("#### 港股规则")
model_name = st.selectbox(
    "筛选模式",
    list(MODEL_LABELS),
    format_func=MODEL_LABELS.get,
)
if model_name == MODEL_YAHOO_10:
    st.info("Yahoo 基础10因子模式不要求自由流通市值；仍保留主板、价格、交易活跃度、停牌和成交额规则。")
saved_settings = {
    **default_filter_settings(model_name),
    **(load_setting(f"risk_filter_{model_name}", {}, DEFAULT_DB_PATH) or {}),
}
cols = st.columns(5)
settings = {
    "main_board_only": cols[0].toggle("只保留主板普通股", bool(saved_settings["main_board_only"])),
    "exclude_gem": cols[1].toggle("排除 GEM", bool(saved_settings["exclude_gem"])),
    "allow_reit": cols[2].toggle("允许 REIT", bool(saved_settings["allow_reit"]), help="REIT不会仅因证券类型被排除，但仍须通过价格、交易活跃度、停牌、成交额及事件风险规则。"),
    "min_price_hkd": cols[3].number_input("最低股价（港元）", 0.0, value=float(saved_settings["min_price_hkd"])),
    "min_listing_days": cols[4].number_input("最低上市交易日", 0, value=int(saved_settings["min_listing_days"])),
}
cols2 = st.columns(4)
settings.update({
    "min_valid_trading_ratio_60d": cols2[0].slider("60日有效交易比例", 0.0, 1.0, float(saved_settings["min_valid_trading_ratio_60d"])),
    "max_suspension_days": cols2[1].number_input("最长连续停牌日", 0, value=int(saved_settings["max_suspension_days"])),
    "min_avg_traded_value_20d": cols2[2].number_input("最低20日平均成交额", 0.0, value=float(saved_settings["min_avg_traded_value_20d"]), format="%.0f"),
    "min_free_float_market_cap": cols2[3].number_input("最低自由流通市值", 0.0, value=float(saved_settings["min_free_float_market_cap"]), format="%.0f"),
    "require_free_float_market_cap": model_name == MODEL_FULL_13,
})
if st.button("保存为因子实验的风险过滤规则", type="primary"):
    save_setting(f"risk_filter_{model_name}", settings, DEFAULT_DB_PATH)
    st.success("规则已保存。以后新建该模式的因子实验时，会在每个月末先执行这套过滤，再计算因子。")
snapshot = build_risk_snapshot(prices, securities, fundamentals)
result = apply_hk_risk_filters(snapshot, settings)
a, b, c = st.columns(3)
a.metric("筛选前", len(snapshot))
b.metric("筛选后", len(result.included))
c.metric("被排除", len(result.excluded))
st.markdown("#### 入选股票")
st.dataframe(localized_frame(result.included), use_container_width=True, hide_index=True)
download_cols = st.columns(2)
download_cols[0].download_button("下载标准字段CSV", result.included.to_csv(index=False).encode("utf-8-sig"), "included_universe.csv")
download_cols[1].download_button("下载中文字段CSV", localized_csv(result.included), "included_universe_cn.csv")
st.info("此处下载仅用于检查和留档。因子实验室会直接读取已保存的风险规则，并逐月过滤证券池；不再需要最后上传两份CSV取交集。")
st.markdown("#### 被排除股票与具体原因")
if result.excluded.empty:
    st.success("当前没有股票被排除。")
else:
    excluded_display = result.excluded[[column for column in ["symbol", "name", "sector", "exclusion_reasons"] if column in result.excluded]]
    st.dataframe(localized_frame(excluded_display), use_container_width=True, hide_index=True)
st.markdown("#### 什么情况下股票仍会被排除")
st.write("即使允许REIT，股票仍可能因以下风险被排除：非主板或GEM、不支持的结构化证券类型、上市历史不足、股价过低、近60日交易活跃度不足、连续停牌超限、最近一年停止派息或大幅削减股息、20日平均成交额不足、完整13因子模式下自由流通市值缺失，以及退市、清盘、私有化或长期停牌事件已经生效。")
st.caption("REIT分派与普通公司股息的经济性质不同，可能受租金收入、利率、资产估值、负债与配售影响；放行仅代表进入量化候选池，最终仍需人工复核公告。港股不使用A股ST制度。")
