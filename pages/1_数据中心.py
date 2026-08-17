from __future__ import annotations

import json
from datetime import date

import pandas as pd
import streamlit as st

from app.config import BENCHMARKS, DEFAULT_DB_PATH
from app.database import connect, export_table_csv, load_setting, read_table, restore_database, save_setting, table_counts, upsert_rows
from app.display import localized_frame
from app.ui import cloud_storage_notice, setup_page, yahoo_notice
from app.stability import universe_fingerprint
from app.universe import validate_universe_csv
from app.yahoo_provider import fetch_benchmark_prices, fetch_yahoo_data


setup_page("数据中心", "🗄️")
if st.session_state.pop("database_restore_complete", False):
    st.success("数据库完整性检查通过并已恢复；旧页面控件状态已清除，请按恢复后的版本继续操作。")
counts = table_counts(DEFAULT_DB_PATH)
c1, c2, c3, c4 = st.columns(4)
c1.metric("证券池", counts["security_master"])
c2.metric("日线记录", counts["daily_prices"])
c3.metric("分红记录", counts["dividends"])
c4.metric("财务记录", counts["fundamentals"])

st.markdown("#### 证券池导入")
universe_file = st.file_uploader("上传证券池 CSV", type=["csv"], help="必须包含 symbol、name、sector、security_type、board、index_membership、effective_date、end_date、source")
if universe_file and st.button("校验并写入证券池", type="primary"):
    try:
        universe = validate_universe_csv(pd.read_csv(universe_file, dtype={"symbol": str}))
        invalid = universe[universe["symbol_error"].notna()]
        valid = universe[universe["symbol_error"].isna()].copy()
        rows = []
        for row in valid.to_dict("records"):
            rows.append({
                "symbol": row["symbol"], "raw_symbol": row["raw_symbol"], "name": row["name"], "sector": row["sector"],
                "listing_date": None, "security_type": row["security_type"], "board": row["board"],
                "index_membership": row["index_membership"], "effective_date": row["effective_date"], "end_date": row["end_date"], "source": row["source"],
            })
        active_symbols = sorted(valid["symbol"].dropna().astype(str).drop_duplicates().tolist())
        universe_version = universe_fingerprint(valid)
        active_payload = {
            "version": universe_version,
            "symbols": active_symbols,
            "row_count": len(active_symbols),
            "file_name": universe_file.name,
            "imported_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        }
        with connect(DEFAULT_DB_PATH) as conn:
            upsert_rows(conn, "security_master", rows)
            upsert_rows(conn, "research_settings", [{
                "setting_key": "active_universe",
                "value_json": json.dumps(active_payload, ensure_ascii=False),
                "updated_at": active_payload["imported_at"],
            }])
        st.session_state["yahoo_symbols_text"] = ", ".join(valid["symbol"].dropna().astype(str).drop_duplicates())
        st.success(f"写入 {len(rows)} 只证券；无效 {len(invalid)} 只。当前活动证券池版本：{universe_version}。")
        if not invalid.empty:
            st.dataframe(localized_frame(invalid[["raw_symbol", "symbol_error"]]), use_container_width=True)
    except Exception as exc:
        st.error(str(exc))

st.markdown("#### 手动 Yahoo 更新")
securities = read_table("security_master", DEFAULT_DB_PATH)
active_universe = load_setting("active_universe", {}, DEFAULT_DB_PATH) or {}
active_symbol_scope = active_universe.get("symbols") or []
if active_symbol_scope:
    all_symbols = sorted({str(symbol) for symbol in active_symbol_scope})
else:
    all_symbols = sorted(securities["symbol"].dropna().astype(str).drop_duplicates().tolist()) if not securities.empty else []
default_symbols = ", ".join(all_symbols)
if "yahoo_symbols_text" not in st.session_state:
    st.session_state["yahoo_symbols_text"] = default_symbols
st.success(f"已从证券池自动载入 {len(all_symbols)} 只港股代码。" if all_symbols else "请先导入证券池，系统会自动生成全部Yahoo港股代码。")
symbols_text = st.text_area(
    "自动生成的港股代码（可编辑，逗号或换行分隔）",
    placeholder="导入证券池后自动生成，例如 0700.HK, 9988.HK, 0005.HK",
    height=180,
    key="yahoo_symbols_text",
)
date_col1, date_col2, batch_col = st.columns(3)
start = date_col1.date_input("原始数据开始日期", value=date(2011, 1, 1), help="若要从2016年开始进行完整10因子月度回测，建议至少从2011年抓取价格与分红历史。")
end = date_col2.date_input("结束日期", value=date.today())
batch_size = batch_col.number_input("每批股票数", 1, 25, 12)
st.caption("回测开始日和原始数据开始日不是同一概念：2011–2015年用于形成历史因子窗口，组合表现从2016年开始评价。")
if st.button("开始更新 Yahoo 数据", type="primary"):
    symbols = [item.strip() for item in symbols_text.replace("\n", ",").split(",") if item.strip()]
    if not symbols:
        st.error("请至少输入一个港股代码。")
    elif start >= end:
        st.error("开始日期必须早于结束日期。")
    else:
        bar, status = st.progress(0.0), st.empty()
        started_at = pd.Timestamp.now(tz="Asia/Shanghai").isoformat()
        with connect(DEFAULT_DB_PATH) as conn:
            cursor = conn.execute(
                """
                INSERT INTO update_logs (
                  started_at, requested_count, success_count, failed_count,
                  failures_json, status
                ) VALUES (?, ?, 0, 0, '[]', 'running')
                """,
                (started_at, len(symbols)),
            )
            update_log_id = int(cursor.lastrowid)
        previous_state = load_setting("market_data_update_state", {}, DEFAULT_DB_PATH) or {}
        save_setting(
            "market_data_update_state",
            {
                "status": "running", "started_at": started_at,
                "requested_count": len(symbols),
                "revision": int(previous_state.get("revision", 0) or 0),
            },
            DEFAULT_DB_PATH,
        )
        def progress(done, total, symbol):
            bar.progress(done / max(total, 1)); status.caption(f"正在处理 {symbol}（{done}/{total}）")
        try:
            def save_batch(batch):
                with connect(DEFAULT_DB_PATH) as conn:
                    upsert_rows(conn, "daily_prices", batch.prices.to_dict("records"))
                    upsert_rows(conn, "dividends", batch.dividends.to_dict("records"))
                    upsert_rows(conn, "corporate_actions", batch.corporate_actions.to_dict("records"))
                    upsert_rows(
                        conn,
                        "security_master",
                        batch.securities.to_dict("records"),
                        preserve_existing_on_null=True,
                    )

            result = fetch_yahoo_data(
                symbols, start, end, batch_size=int(batch_size), progress=progress,
                batch_sink=save_batch,
            )
            finished_at = pd.Timestamp.now(tz="Asia/Shanghai").isoformat()
            final_status = "completed_with_warnings" if result.failures else "completed"
            failure_payload = json.dumps([failure.__dict__ for failure in result.failures], ensure_ascii=False)
            with connect(DEFAULT_DB_PATH) as conn:
                conn.execute(
                    """
                    UPDATE update_logs
                    SET finished_at = ?, success_count = ?, failed_count = ?,
                        failures_json = ?, status = ?
                    WHERE id = ?
                    """,
                    (finished_at, result.success_count, len(result.failures), failure_payload, final_status, update_log_id),
                )
            save_setting(
                "market_data_update_state",
                {
                    "status": final_status, "started_at": started_at,
                    "finished_at": finished_at, "requested_count": len(symbols),
                    "success_count": result.success_count,
                    "failed_count": len(result.failures),
                    "revision": int(previous_state.get("revision", 0) or 0) + int(result.price_row_count > 0),
                },
                DEFAULT_DB_PATH,
            )
            st.success(f"更新完成：价格 {result.price_row_count:,} 行，分红 {result.dividend_row_count:,} 行，公司行动 {result.action_row_count:,} 行。")
            if result.failures:
                st.warning("部分股票失败，任务其余部分已保存。")
                st.dataframe(localized_frame(pd.DataFrame([failure.__dict__ for failure in result.failures])), use_container_width=True)
        except Exception as exc:
            finished_at = pd.Timestamp.now(tz="Asia/Shanghai").isoformat()
            with connect(DEFAULT_DB_PATH) as conn:
                conn.execute(
                    "UPDATE update_logs SET finished_at = ?, status = ?, failures_json = ? WHERE id = ?",
                    (finished_at, "failed", json.dumps([{"reason": str(exc)}], ensure_ascii=False), update_log_id),
                )
            save_setting(
                "market_data_update_state",
                {
                    "status": "failed", "started_at": started_at,
                    "finished_at": finished_at, "requested_count": len(symbols),
                    "revision": int(previous_state.get("revision", 0) or 0),
                    "reason": str(exc),
                },
                DEFAULT_DB_PATH,
            )
            st.error(f"Yahoo 更新未完成：{exc}")

if st.button("更新已验证基准指数（恒指 / 国企指数）"):
    try:
        benchmark_state = load_setting("benchmark_data_update_state", {}, DEFAULT_DB_PATH) or {}
        benchmark_prices, failures = fetch_benchmark_prices(BENCHMARKS.values(), start, end)
        with connect(DEFAULT_DB_PATH) as conn:
            upsert_rows(conn, "daily_prices", benchmark_prices.to_dict("records"))
        save_setting(
            "benchmark_data_update_state",
            {
                "status": "completed_with_warnings" if failures else "completed",
                "updated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
                "revision": int(benchmark_state.get("revision", 0) or 0) + int(not benchmark_prices.empty),
                "failed_count": len(failures),
            },
            DEFAULT_DB_PATH,
        )
        st.success(f"基准更新完成：{len(benchmark_prices):,} 行。")
        if failures:
            st.warning("；".join(f"{item.symbol}: {item.reason}" for item in failures))
    except Exception as exc:
        st.error(f"基准更新失败：{exc}")
st.caption("Yahoo 基准代码 ^HSI 与 ^HSCE 已于 2026-08-06 通过五日只读请求验证；Yahoo 后续仍可能变更代码或可用性。")

st.markdown("#### 导入导出与缓存备份")
cloud_storage_notice()
st.caption("为避免大型价格表在每次页面刷新时占用内存，导出文件只在明确点击后生成；完整留档优先选择SQLite备份。")
export_kind = st.selectbox(
    "准备下载内容",
    ["价格 CSV", "因子 CSV", "实验 CSV", "SQLite 备份"],
)
if st.button("生成所选下载文件"):
    export_map = {
        "价格 CSV": ("daily_prices.csv", "text/csv", lambda: export_table_csv("daily_prices")),
        "因子 CSV": ("monthly_features.csv", "text/csv", lambda: export_table_csv("monthly_features")),
        "实验 CSV": ("experiments.csv", "text/csv", lambda: export_table_csv("experiments")),
        "SQLite 备份": (
            "hk_dividend_lab.sqlite3", "application/x-sqlite3",
            lambda: DEFAULT_DB_PATH.read_bytes(),
        ),
    }
    filename, mime, producer = export_map[export_kind]
    if export_kind == "SQLite 备份" and not DEFAULT_DB_PATH.exists():
        st.error("当前还没有可下载的SQLite数据库。")
    else:
        with st.spinner("正在生成下载文件……"):
            payload = producer()
        st.download_button(
            f"下载 {export_kind}", payload, file_name=filename, mime=mime,
            on_click="ignore",
        )
backup = st.file_uploader("上传 SQLite 备份恢复（将替换当前运行缓存）", type=["sqlite", "sqlite3", "db"])
if backup and st.button("检查并恢复 SQLite"):
    try:
        restore_database(backup.getvalue(), DEFAULT_DB_PATH)
        for key in list(st.session_state):
            if key.startswith((
                "main_board_only_", "exclude_gem_", "allow_reit_",
                "min_price_hkd_", "min_listing_days_",
                "min_valid_trading_ratio_60d_", "max_suspension_days_",
                "min_avg_traded_value_20d_", "min_free_float_market_cap_",
                "weight_",
            )) or key in {"yahoo_symbols_text", "active_experiment_id"}:
                del st.session_state[key]
        st.session_state["database_restore_complete"] = True
        st.rerun()
    except Exception as exc:
        st.error(str(exc))
yahoo_notice()
