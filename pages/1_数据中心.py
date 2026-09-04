from __future__ import annotations

import json
from datetime import date
from io import StringIO

import pandas as pd
import streamlit as st

from app.config import BENCHMARKS, DATA_DIR, DEFAULT_DB_PATH
from app.cloud_persistence import read_latest_manifest, resolve_cloud_config, restore_database_from_cloud
from app.database import connect, export_table_csv, load_setting, read_table, save_setting, table_counts, upsert_rows
from app.display import localized_frame, stable_html_table
from app.cloud_ui import cloud_storage_notice, persist_cloud_database
from app.page_runtime import setup_page
from app.ui import yahoo_notice
from app.stability import universe_fingerprint
from app.universe import validate_universe_csv
from app.yahoo_provider import fetch_benchmark_prices, fetch_yahoo_data


setup_page("数据中心", "🗄️")
if st.session_state.pop("database_restore_complete", False):
    st.success("数据库完整性检查通过并已恢复；旧页面控件状态已清除，请按恢复后的版本继续操作。")
if import_notice := st.session_state.pop("universe_import_notice", None):
    st.success(import_notice)
if invalid_records := st.session_state.pop("universe_invalid_records", None):
    st.warning(f"另有 {len(invalid_records)} 行证券代码无效，未写入证券池。")
    st.markdown(stable_html_table(localized_frame(pd.DataFrame(invalid_records))), unsafe_allow_html=True)
counts = table_counts(DEFAULT_DB_PATH)
c1, c2, c3, c4 = st.columns(4)
c1.metric("证券池", counts["security_master"])
c2.metric("日线记录", counts["daily_prices"])
c3.metric("分红记录", counts["dividends"])
c4.metric("财务记录", counts["fundamentals"])

BUILTIN_UNIVERSE_PATH = DATA_DIR / "current_hsi_hscei_universe.csv"


def persist_universe(frame: pd.DataFrame, file_name: str) -> tuple[int, pd.DataFrame, str]:
    universe = validate_universe_csv(frame)
    invalid = universe[universe["symbol_error"].notna()].copy()
    valid = universe[universe["symbol_error"].isna()].copy()
    if valid.empty:
        raise ValueError("证券池中没有可写入的有效港股代码。")
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
        "file_name": file_name,
        "imported_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
    }
    with connect(DEFAULT_DB_PATH) as conn:
        upsert_rows(conn, "security_master", rows)
        upsert_rows(conn, "research_settings", [{
            "setting_key": "active_universe",
            "value_json": json.dumps(active_payload, ensure_ascii=False),
            "updated_at": active_payload["imported_at"],
        }])
    st.session_state["yahoo_symbols_text"] = ", ".join(active_symbols)
    return len(rows), invalid, universe_version


def finish_universe_import(row_count: int, invalid: pd.DataFrame, universe_version: str) -> None:
    st.session_state["universe_import_notice"] = (
        f"写入 {row_count} 只证券；无效 {len(invalid)} 只。当前活动证券池版本：{universe_version}。"
    )
    if not invalid.empty:
        st.session_state["universe_invalid_records"] = invalid[["raw_symbol", "symbol_error"]].to_dict("records")
    persist_cloud_database("universe_import")
    st.rerun()


st.markdown("#### 证券池导入")
st.caption("客户演示建议使用内置证券池：无需调用浏览器文件上传模块，内容为2026-09-07生效的恒指及国企指数最新并集。")
if st.button("一键载入内置最新证券池（104只）", type="primary"):
    try:
        builtin_frame = pd.read_csv(BUILTIN_UNIVERSE_PATH, dtype={"symbol": str})
        finish_universe_import(*persist_universe(builtin_frame, BUILTIN_UNIVERSE_PATH.name))
    except Exception as exc:
        st.error(f"内置证券池载入失败：{exc}")

if st.button("显示或隐藏自定义证券池 CSV 文本导入工具"):
    st.session_state["show_custom_universe_upload"] = not st.session_state.get("show_custom_universe_upload", False)
if st.session_state.get("show_custom_universe_upload", False):
    st.info("为避免云端部署或休眠唤醒后文件上传组件加载失败，请用文本编辑器打开 CSV，复制全部内容并粘贴到下方。")
    custom_csv_text = st.text_area(
        "粘贴证券池 CSV 完整内容",
        height=220,
        key="custom_universe_csv_text",
        placeholder="symbol,name,sector,security_type,board,index_membership,effective_date,end_date,source",
        help="必须包含 symbol、name、sector、security_type、board、index_membership、effective_date、end_date、source",
    )
    if st.button("校验并写入自定义证券池"):
        try:
            if not custom_csv_text.strip():
                raise ValueError("请先粘贴证券池 CSV 的完整内容。")
            custom_frame = pd.read_csv(StringIO(custom_csv_text.lstrip("\ufeff")), dtype={"symbol": str})
            finish_universe_import(*persist_universe(custom_frame, "pasted_universe.csv"))
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
st.caption("原始数据开始日期（年 / 月 / 日）")
start_cols = st.columns(3)
start_year = start_cols[0].number_input("开始年", 2000, date.today().year, 2011, step=1)
start_month = start_cols[1].number_input("开始月", 1, 12, 1, step=1)
start_day = start_cols[2].number_input("开始日", 1, 31, 1, step=1)
st.caption("结束日期（年 / 月 / 日）")
end_cols = st.columns(3)
end_year = end_cols[0].number_input("结束年", 2000, date.today().year + 1, date.today().year, step=1)
end_month = end_cols[1].number_input("结束月", 1, 12, date.today().month, step=1)
end_day = end_cols[2].number_input("结束日", 1, 31, date.today().day, step=1)
batch_size = st.number_input("每批股票数", 1, 25, 12)
date_error = None
try:
    start = date(int(start_year), int(start_month), int(start_day))
    end = date(int(end_year), int(end_month), int(end_day))
    if start > end:
        date_error = "原始数据开始日期不能晚于结束日期。"
except ValueError:
    date_error = "日期无效，请检查年月日（例如二月没有30日）。"
if date_error:
    st.error(date_error)
st.caption("回测开始日和原始数据开始日不是同一概念：2011–2015年用于形成历史因子窗口，组合表现从2016年开始评价。")
if st.button("开始更新 Yahoo 数据", type="primary", disabled=bool(date_error)):
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
            persist_cloud_database("yahoo_market_data_update")
            if result.failures:
                st.warning("部分股票失败，任务其余部分已保存。")
                st.markdown(
                    stable_html_table(localized_frame(pd.DataFrame([failure.__dict__ for failure in result.failures]))),
                    unsafe_allow_html=True,
                )
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
        persist_cloud_database("benchmark_data_update")
        if failures:
            st.warning("；".join(f"{item.symbol}: {item.reason}" for item in failures))
    except Exception as exc:
        st.error(f"基准更新失败：{exc}")
st.caption("Yahoo 基准代码 ^HSI 与 ^HSCE 已于 2026-08-06 通过五日只读请求验证；Yahoo 后续仍可能变更代码或可用性。")

st.markdown("#### 导入导出与缓存备份")
cloud_storage_notice()
cloud_config = resolve_cloud_config(st.secrets)
if cloud_config.configured:
    st.success(f"云端持久化已启用：私有存储桶 `{cloud_config.bucket}`。密钥只从 Streamlit Secrets 读取，不会显示在页面或写入数据库。")
    cloud_actions = st.columns(2)
    if cloud_actions[0].button("立即备份到云端", type="primary"):
        result = persist_cloud_database("manual_backup")
        if result.ok:
            st.success(result.message)
        else:
            st.error(result.message)
    if cloud_actions[1].button("检查云端最新备份"):
        try:
            manifest = read_latest_manifest(cloud_config)
            if manifest:
                st.info(
                    f"最新云端备份：{manifest.get('created_at', '未知时间')}；"
                    f"原因：{manifest.get('reason', '未知')}；"
                    f"完整大小：{int(manifest.get('raw_size', 0)) / 1024 / 1024:.1f} MB；"
                    f"{'受保护正式版本' if manifest.get('protected') else '普通版本'}。"
                )
            else:
                st.info("云端尚无数据库备份，可点击左侧按钮创建第一份。")
        except Exception as exc:
            st.error(f"读取云端备份状态失败：{exc}")
    confirm_cloud_restore = st.checkbox("我确认从云端恢复会替换当前运行缓存（云端历史文件不会被删除）")
    if st.button("从云端恢复最新数据库", disabled=not confirm_cloud_restore):
        result = restore_database_from_cloud(DEFAULT_DB_PATH, st.secrets, force=True)
        if result.ok and result.action == "restore":
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
            st.session_state["cloud_persistence_notice"] = ("success", result.message)
            st.rerun()
        else:
            st.error(result.message)
else:
    st.warning("云端持久化尚未启用。请按 README 的说明配置 SUPABASE_URL、SUPABASE_SECRET_KEY 与 SUPABASE_STORAGE_BUCKET；在此之前请继续下载 SQLite 离线备份。")
st.caption("为避免大型价格表在每次页面刷新时占用内存，导出文件只在明确点击后生成；完整留档优先选择SQLite备份。")
export_options = ["价格 CSV", "因子 CSV", "实验 CSV", "SQLite 备份"]
if st.session_state.get("data_export_kind") not in export_options:
    st.session_state["data_export_kind"] = export_options[0]
st.write("准备下载内容")
export_columns = st.columns(len(export_options))
for export_column, option in zip(export_columns, export_options):
    if export_column.button(
        option,
        key=f"choose_data_export_{option}",
        type="primary" if st.session_state["data_export_kind"] == option else "secondary",
        use_container_width=True,
    ):
        st.session_state["data_export_kind"] = option
export_kind = st.session_state["data_export_kind"]
st.caption(f"当前选择：{export_kind}")
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
st.caption(
    "为避免云端部署或休眠唤醒后浏览器上传模块加载失败，本页不再加载 SQLite 文件上传控件。"
    "需要恢复时请使用上方“从云端恢复最新数据库”；下载的 SQLite 文件仍可作为离线灾备交由管理员恢复。"
)
yahoo_notice()
