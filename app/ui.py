from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from .config import APP_NAME, APP_SUBTITLE, DEFAULT_DB_PATH
from .data_quality import database_quality_snapshot
from .database import initialize_database, load_setting


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
</style>
"""


def setup_page(title: str, icon: str = "📊") -> dict:
    st.set_page_config(page_title=f"{title} | {APP_NAME}", page_icon=icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
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
        st.warning("市场数据正在更新。已保存实验仍可查看，但请等待更新完成后再创建新的风险快照或因子实验。")
    if snapshot["quality_note"]:
        st.warning(snapshot["quality_note"])
    return snapshot


def empty_state(message: str = "尚无可计算的真实数据。请先前往“数据中心”导入证券池并手动更新 Yahoo 数据。") -> None:
    st.info(message)


def yahoo_notice() -> None:
    st.caption("Yahoo Finance 数据通过非官方 yfinance 工具获取，可能受许可条款、限流、字段变化和服务稳定性影响；抓取失败会被明确记录。")


def cloud_storage_notice() -> None:
    st.caption("Streamlit Community Cloud 的本地 SQLite 仅作为运行缓存，不是永久存储。请定期下载数据库备份，并在应用重启后手动恢复。")
