from __future__ import annotations

from html import escape
from time import time

import pandas as pd
import streamlit as st

from .config import APP_NAME, APP_SUBTITLE, DEFAULT_DB_PATH
from .data_quality import database_quality_snapshot
from .database import initialize_database, load_setting
from .update_progress import format_duration, update_progress_metrics


CSS = """
<style>
  :root { --forest:#164E3B; --cream:#F6F1E7; --ink:#1C2A25; --muted:#65746D; --warn:#C76D2E; }
  [data-testid="stAppViewContainer"] { background: linear-gradient(180deg,#F8F5EE 0,#F2F3EF 100%); color:var(--ink); }
  [data-testid="stSidebar"] { background:#123B30; }
  [data-testid="stSidebar"] * { color:#F6F1E7; }
  .lab-kicker { color:#507264; text-transform:uppercase; letter-spacing:.16em; font-size:.72rem; font-weight:700; }
  .lab-title { font-family:Georgia,'Noto Serif SC',serif; color:var(--forest); font-size:2.45rem; line-height:1.05; margin:.3rem 0; }
  .lab-subtitle { color:var(--muted); font-size:.95rem; margin-bottom:1.6rem; }
  .quality-strip { border-left:4px solid var(--forest); background:#FFFDF8; padding:.8rem 1rem; border-radius:.35rem; margin:.6rem 0 1.4rem; }
  .oos-tag { display:inline-block; background:#DDEBE3; color:#164E3B; border-radius:99px; padding:.2rem .65rem; font-weight:700; font-size:.72rem; }
  .warning-box { border-left:4px solid var(--warn); background:#FFF5E9; padding:.8rem 1rem; border-radius:.35rem; }
  div[data-testid="stMetric"] { background:#FFFDF8; border:1px solid #DDE3DC; padding:1rem; border-radius:.65rem; }
  div[data-testid="stDataFrame"] { border:1px solid #D9DED8; border-radius:.55rem; overflow:hidden; }
  .stable-table-wrap { max-height:34rem; overflow:auto; background:#FFFDF8; border:1px solid #D9DED8; border-radius:.55rem; }
  .stable-table { width:100%; border-collapse:separate; border-spacing:0; font-size:.86rem; }
  .stable-table th { position:sticky; top:0; z-index:1; padding:.7rem .8rem; color:#44534D; background:#EDF1EF; border-bottom:1px solid #D9DED8; text-align:left; white-space:nowrap; }
  .stable-table td { padding:.62rem .8rem; border-bottom:1px solid #E6EAE5; vertical-align:top; white-space:nowrap; }
  .stable-table tbody tr:nth-child(even) { background:#FAFBF8; }
  .stable-table tbody tr:hover { background:#F1F6F2; }
  .stable-table-empty { padding:1rem; color:var(--muted); background:#FFFDF8; border:1px solid #D9DED8; border-radius:.55rem; }
  .stable-table-note { margin:.4rem 0 0; color:var(--muted); font-size:.78rem; }
  .update-progress-card { background:#FFFDF8; border:1px solid #D7E1DA; border-left:4px solid var(--forest); border-radius:.55rem; padding:.85rem 1rem; margin:.7rem 0 1rem; }
  .update-progress-head { display:flex; justify-content:space-between; gap:1rem; align-items:baseline; font-weight:700; }
  .update-progress-percent { color:var(--forest); font-size:1.25rem; }
  .update-progress-track { height:.72rem; margin:.65rem 0; background:#E5ECE7; border-radius:99px; overflow:hidden; }
  .update-progress-fill { height:100%; background:linear-gradient(90deg,#1D7256,#47A276); border-radius:99px; transition:width .35s ease; }
  .update-progress-stats { display:flex; flex-wrap:wrap; gap:.35rem 1.15rem; color:#44534D; font-size:.87rem; }
  .update-progress-detail { margin-top:.45rem; color:var(--muted); font-size:.8rem; }
</style>
"""


def market_update_progress_html(update_state: dict) -> str:
    metrics = update_progress_metrics(update_state)
    percent = metrics["percent"]
    latest = escape(metrics["current_symbol"] or "尚未完成第一只股票")
    phase = escape(metrics["phase"])
    heartbeat = metrics["seconds_since_update"]
    heartbeat_text = format_duration(heartbeat) if heartbeat is not None else "未知"
    return f"""
    <div class="update-progress-card" role="status" aria-live="polite">
      <div class="update-progress-head">
        <span>Yahoo 市场数据更新进度</span>
        <span class="update-progress-percent">{percent:.1f}%</span>
      </div>
      <div class="update-progress-track" aria-label="更新进度 {percent:.1f}%">
        <div class="update-progress-fill" style="width:{percent:.1f}%"></div>
      </div>
      <div class="update-progress-stats">
        <span>已处理 <b>{metrics['completed']}</b> / {metrics['total']} 只</span>
        <span>剩余 <b>{metrics['remaining']}</b> 只</span>
        <span>已用 {format_duration(metrics['elapsed_seconds'])}</span>
        <span>预计剩余 {format_duration(metrics['eta_seconds'])}</span>
      </div>
      <div class="update-progress-detail">{phase}　·　最近完成：{latest}　·　状态于 {heartbeat_text} 前更新</div>
    </div>
    """


@st.fragment(run_every="2s")
def market_update_progress_panel() -> None:
    update_state = load_setting("market_data_update_state", {}, DEFAULT_DB_PATH) or {}
    if update_state.get("status") == "running":
        st.markdown(market_update_progress_html(update_state), unsafe_allow_html=True)
    elif update_state.get("status") in {"completed", "completed_with_warnings"}:
        failed_count = int(update_state.get("failed_count", 0) or 0)
        suffix = f"，其中 {failed_count} 只失败" if failed_count else ""
        st.success(f"Yahoo 市场数据更新已完成{suffix}。请刷新本页继续计算风险快照。")
    elif update_state.get("status") == "failed":
        st.error("Yahoo 市场数据更新已中断。请返回数据中心查看错误并重新运行。")


def setup_page(title: str, icon: str = "📊") -> dict:
    st.set_page_config(page_title=f"{title} | {APP_NAME}", page_icon=icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.sidebar.page_link(
        "https://spring-stock-app.vercel.app/",
        label="返回 SIP 网站首页",
        icon="🏠",
    )
    fresh_url = f"https://hk-dividend-low-vol-lab.streamlit.app/?reload={int(time() * 1000)}"
    st.sidebar.markdown(f"[🔄 页面出现红色组件错误？重新加载最新版本]({fresh_url})")
    st.sidebar.caption("部署或休眠唤醒后如有组件加载失败，请使用上方入口打开全新会话。")
    st.sidebar.divider()
    initialize_database(DEFAULT_DB_PATH)
    st.markdown('<div class="lab-kicker">HK EQUITY RESEARCH TERMINAL</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="lab-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="lab-subtitle">{APP_SUBTITLE}</div>', unsafe_allow_html=True)
    snapshot = database_quality_snapshot(DEFAULT_DB_PATH)
    active_universe = load_setting("active_universe", {}, DEFAULT_DB_PATH) or {}
    update_state = load_setting("market_data_update_state", {}, DEFAULT_DB_PATH) or {}
    cutoff = snapshot["data_cutoff"].date().isoformat() if pd.notna(snapshot["data_cutoff"]) else "尚无数据"
    st.markdown(f'<div class="quality-strip">数据截止：<b>{cutoff}</b>　·　价格覆盖 {snapshot["price_coverage"]:.0%}　·　分红覆盖 {snapshot["dividend_coverage"]:.0%}　·　财务覆盖 {snapshot["fundamental_coverage"]:.0%}</div>', unsafe_allow_html=True)
    if active_universe:
        st.caption(
            f"当前活动证券池：{active_universe.get('version', '未知版本')}（{int(active_universe.get('row_count', 0) or 0)}只）"
            f"　·　市场数据修订版：R{int(update_state.get('revision', 0) or 0)}"
        )
    if update_state.get("status") == "running":
        market_update_progress_panel()
        st.warning("更新期间已保存实验仍可查看；请等待进度达到100%后，再创建新的风险快照或因子实验。")
    if snapshot["quality_note"]:
        st.warning(snapshot["quality_note"])
    return snapshot


def empty_state(message: str = "尚无可计算的真实数据。请先前往“数据中心”导入证券池并手动更新 Yahoo 数据。") -> None:
    st.info(message)


def yahoo_notice() -> None:
    st.caption("Yahoo Finance 数据通过非官方 yfinance 工具获取，可能受许可条款、限流、字段变化和服务稳定性影响；抓取失败会被明确记录。")
