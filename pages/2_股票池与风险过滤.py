from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import DEFAULT_DB_PATH, MODEL_FULL_13, MODEL_LABELS, MODEL_YAHOO_10
from app.database import load_setting, read_table, save_setting
from app.display import localized_csv, localized_frame
from app.stability import read_recent_stock_prices, resolve_stock_data_cutoff, risk_snapshot_fingerprint
from app.ui import empty_state, setup_page
from app.universe import apply_hk_risk_filters, build_risk_snapshot, default_filter_settings


setup_page("股票池与风险过滤", "🧹")
active_universe = load_setting("active_universe", {}, DEFAULT_DB_PATH) or {}
active_symbols = sorted({str(symbol) for symbol in active_universe.get("symbols", []) if symbol})
security_filters = {"symbol": active_symbols} if active_symbols else None
securities = read_table("security_master", DEFAULT_DB_PATH, filters=security_filters)
if not active_symbols and not securities.empty:
    active_symbols = sorted(securities["symbol"].dropna().astype(str).unique().tolist())
    st.warning("当前数据库来自旧版本，尚无活动证券池版本记录；本页暂时使用证券主表全部股票。建议在数据中心重新导入一次证券池CSV。")

update_state = load_setting("market_data_update_state", {}, DEFAULT_DB_PATH) or {}
if update_state.get("status") == "running":
    started = pd.to_datetime(update_state.get("started_at"), errors="coerce", utc=True)
    age_hours = (pd.Timestamp.now(tz="UTC") - started).total_seconds() / 3600 if pd.notna(started) else 0
    if age_hours < 6:
        st.warning("Yahoo 数据仍在分批更新。为避免读取半完成数据，风险快照暂不计算；请等待数据中心显示更新完成后再刷新本页。")
        st.stop()
    st.warning("检测到超过6小时未结束的旧更新状态，将按当前已完成的数据版本继续计算；建议到数据中心重新运行更新并检查失败日志。")

cutoff_meta = resolve_stock_data_cutoff(DEFAULT_DB_PATH, active_symbols)
data_cutoff = cutoff_meta.get("as_of")
prices = read_recent_stock_prices(
    DEFAULT_DB_PATH, 60, symbols=active_symbols, as_of=data_cutoff,
)
fundamentals = read_table("fundamentals", DEFAULT_DB_PATH, filters=security_filters)
if securities.empty or prices.empty:
    empty_state()
    st.stop()

universe_version = str(active_universe.get("version") or "legacy-all")
data_revision = int(update_state.get("revision", 0) or 0)
coverage_denominator = len(active_symbols) or len(securities)
st.caption(
    f"活动证券池版本：{universe_version}　·　统一价格截止日：{data_cutoff or '未知'}　·　"
    f"数据修订版：R{data_revision}　·　已有价格：{cutoff_meta.get('available_symbols', 0)}/{coverage_denominator}只"
)
if cutoff_meta.get("available_symbols", 0) < coverage_denominator:
    st.warning("部分活动证券尚无价格记录；它们会以“价格或交易数据缺失”被明确排除，不会被静默忽略。")
if update_state.get("status") == "completed_with_warnings":
    st.warning(f"最近一次Yahoo更新有 {int(update_state.get('failed_count', 0) or 0)} 只失败；当前快照沿用这些股票已有的旧数据，请先查看数据中心失败清单。")

st.markdown("#### 港股规则")
model_name = st.selectbox(
    "筛选模式",
    list(MODEL_LABELS),
    format_func=MODEL_LABELS.get,
)
if model_name == MODEL_YAHOO_10:
    st.info("Yahoo 基础10因子模式不要求自由流通市值；仍保留主板、价格、交易活跃度、停牌和成交额规则。")
stored_settings = load_setting(f"risk_filter_{model_name}", {}, DEFAULT_DB_PATH) or {}
saved_settings = {
    **default_filter_settings(model_name),
    **stored_settings,
}
with st.form(f"risk_filter_form_{model_name}"):
    cols = st.columns(5)
    candidate_settings = {
        "main_board_only": cols[0].toggle("只保留主板普通股", bool(saved_settings["main_board_only"]), key=f"main_board_only_{model_name}"),
        "exclude_gem": cols[1].toggle("排除 GEM", bool(saved_settings["exclude_gem"]), key=f"exclude_gem_{model_name}"),
        "allow_reit": cols[2].toggle("允许 REIT", bool(saved_settings["allow_reit"]), key=f"allow_reit_{model_name}", help="REIT不会仅因证券类型被排除，但仍须通过价格、交易活跃度、停牌、成交额及事件风险规则。"),
        "min_price_hkd": cols[3].number_input("最低股价（港元）", 0.0, value=float(saved_settings["min_price_hkd"]), key=f"min_price_hkd_{model_name}"),
        "min_listing_days": cols[4].number_input("最低上市交易日", 0, value=int(saved_settings["min_listing_days"]), key=f"min_listing_days_{model_name}"),
    }
    cols2 = st.columns(4)
    candidate_settings.update({
        "min_valid_trading_ratio_60d": cols2[0].slider("60日有效交易比例", 0.0, 1.0, float(saved_settings["min_valid_trading_ratio_60d"]), key=f"min_valid_trading_ratio_60d_{model_name}"),
        "max_suspension_days": cols2[1].number_input("最长连续停牌日", 0, value=int(saved_settings["max_suspension_days"]), key=f"max_suspension_days_{model_name}"),
        "min_avg_traded_value_20d": cols2[2].number_input("最低20日平均成交额", 0.0, value=float(saved_settings["min_avg_traded_value_20d"]), format="%.0f", key=f"min_avg_traded_value_20d_{model_name}"),
        "min_free_float_market_cap": cols2[3].number_input("最低自由流通市值", 0.0, value=float(saved_settings["min_free_float_market_cap"]), format="%.0f", key=f"min_free_float_market_cap_{model_name}"),
        "require_free_float_market_cap": model_name == MODEL_FULL_13,
    })
    submitted = st.form_submit_button("应用并保存为因子实验的风险过滤规则", type="primary")
if submitted:
    candidate_settings.update({
        "_universe_version": universe_version,
        "_data_revision": data_revision,
        "_data_cutoff": data_cutoff,
        "_saved_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
    })
    save_setting(f"risk_filter_{model_name}", candidate_settings, DEFAULT_DB_PATH)
    st.success("规则及其数据版本已保存。页面将只使用已保存规则计算，避免未提交的控件变化影响结果。")
    st.rerun()

settings = {
    key: saved_settings[key]
    for key in default_filter_settings(model_name)
}
snapshot = build_risk_snapshot(prices, securities, fundamentals)
result = apply_hk_risk_filters(snapshot, settings)
snapshot_version = risk_snapshot_fingerprint(
    snapshot, settings, as_of=data_cutoff, universe_version=universe_version,
)
st.markdown(f'<span class="oos-tag">风险快照 {snapshot_version}</span>', unsafe_allow_html=True)
if not stored_settings:
    st.info("当前使用系统默认规则。若要让后续因子实验读取同一套规则，请点击上方“应用并保存”。")
elif stored_settings.get("_universe_version") not in {None, universe_version}:
    st.warning("风险规则是在另一证券池版本下保存的。当前页面已用相同规则重新计算；建议检查后再次保存，以绑定当前证券池版本。")
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
