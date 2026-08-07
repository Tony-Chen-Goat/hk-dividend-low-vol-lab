from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.config import BENCHMARKS, DEFAULT_DB_PATH
from app.database import connect, export_table_csv, initialize_database, read_table, restore_database, table_counts, upsert_rows
from app.ui import cloud_storage_notice, setup_page, yahoo_notice
from app.universe import validate_universe_csv
from app.yahoo_provider import fetch_benchmark_prices, fetch_yahoo_data


setup_page("数据中心", "🗄️")
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
        with connect(DEFAULT_DB_PATH) as conn:
            upsert_rows(conn, "security_master", rows)
        st.success(f"写入 {len(rows)} 只证券；无效 {len(invalid)} 只。")
        if not invalid.empty:
            st.dataframe(invalid[["raw_symbol", "symbol_error"]], use_container_width=True)
    except Exception as exc:
        st.error(str(exc))

st.markdown("#### 手动 Yahoo 更新")
securities = read_table("security_master", DEFAULT_DB_PATH)
default_symbols = ", ".join(securities["symbol"].head(12).tolist()) if not securities.empty else ""
symbols_text = st.text_area("港股代码（逗号或换行分隔）", value=default_symbols, placeholder="700, 9988, 0005.HK")
date_col1, date_col2, batch_col = st.columns(3)
start = date_col1.date_input("开始日期", value=date.today() - timedelta(days=365 * 6))
end = date_col2.date_input("结束日期", value=date.today())
batch_size = batch_col.number_input("每批股票数", 1, 25, 12)
if st.button("开始更新 Yahoo 数据", type="primary"):
    symbols = [item.strip() for item in symbols_text.replace("\n", ",").split(",") if item.strip()]
    if not symbols:
        st.error("请至少输入一个港股代码。")
    elif start >= end:
        st.error("开始日期必须早于结束日期。")
    else:
        bar, status = st.progress(0.0), st.empty()
        def progress(done, total, symbol):
            bar.progress(done / max(total, 1)); status.caption(f"正在处理 {symbol}（{done}/{total}）")
        try:
            result = fetch_yahoo_data(symbols, start, end, batch_size=int(batch_size), progress=progress)
            with connect(DEFAULT_DB_PATH) as conn:
                upsert_rows(conn, "daily_prices", result.prices.to_dict("records"))
                upsert_rows(conn, "dividends", result.dividends.to_dict("records"))
                upsert_rows(conn, "corporate_actions", result.corporate_actions.to_dict("records"))
                upsert_rows(conn, "security_master", result.securities.to_dict("records"))
                upsert_rows(conn, "update_logs", [{
                    "started_at": pd.Timestamp.now().isoformat(), "finished_at": pd.Timestamp.now().isoformat(),
                    "requested_count": len(symbols), "success_count": result.prices["symbol"].nunique() if not result.prices.empty else 0,
                    "failed_count": len(result.failures), "failures_json": json.dumps([failure.__dict__ for failure in result.failures], ensure_ascii=False),
                    "status": "completed_with_warnings" if result.failures else "completed",
                }])
            st.success(f"更新完成：价格 {len(result.prices):,} 行，分红 {len(result.dividends):,} 行，公司行动 {len(result.corporate_actions):,} 行。")
            if result.failures:
                st.warning("部分股票失败，任务其余部分已保存。")
                st.dataframe(pd.DataFrame([failure.__dict__ for failure in result.failures]), use_container_width=True)
        except Exception as exc:
            st.error(f"Yahoo 更新未完成：{exc}")

if st.button("更新已验证基准指数（恒指 / 国企指数）"):
    try:
        benchmark_prices, failures = fetch_benchmark_prices(BENCHMARKS.values(), start, end)
        with connect(DEFAULT_DB_PATH) as conn:
            upsert_rows(conn, "daily_prices", benchmark_prices.to_dict("records"))
        st.success(f"基准更新完成：{len(benchmark_prices):,} 行。")
        if failures:
            st.warning("；".join(f"{item.symbol}: {item.reason}" for item in failures))
    except Exception as exc:
        st.error(f"基准更新失败：{exc}")
st.caption("Yahoo 基准代码 ^HSI 与 ^HSCE 已于 2026-08-06 通过五日只读请求验证；Yahoo 后续仍可能变更代码或可用性。")

st.markdown("#### 导入导出与缓存备份")
cloud_storage_notice()
download_cols = st.columns(4)
for column, table, label in zip(download_cols, ["daily_prices", "monthly_features", "experiments"], ["价格 CSV", "因子 CSV", "实验 CSV"]):
    column.download_button(label, export_table_csv(table), file_name=f"{table}.csv", mime="text/csv")
if DEFAULT_DB_PATH.exists():
    download_cols[3].download_button("SQLite 备份", DEFAULT_DB_PATH.read_bytes(), file_name="hk_dividend_lab.sqlite3", mime="application/x-sqlite3")
backup = st.file_uploader("上传 SQLite 备份恢复（将替换当前运行缓存）", type=["sqlite", "sqlite3", "db"])
if backup and st.button("检查并恢复 SQLite"):
    try:
        restore_database(backup.getvalue(), DEFAULT_DB_PATH)
        st.success("数据库完整性检查通过并已恢复。")
    except Exception as exc:
        st.error(str(exc))
yahoo_notice()
