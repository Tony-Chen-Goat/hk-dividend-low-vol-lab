from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from .cloud_persistence import (
    PersistenceResult,
    backup_database_to_cloud,
    bootstrap_cloud_database,
    seed_cloud_database_once,
)
from .config import DEFAULT_DB_PATH


_RESTORE_STATE_KEY = "cloud_persistence_restore_result"


def prepare_cloud_database(secrets: Mapping[str, Any] | None = None) -> PersistenceResult:
    """Restore the runtime database before the page initializes SQLite.

    This intentionally lives outside ``app.ui``. Streamlit Cloud can rerun page
    scripts after a Git pull while retaining already-imported Python modules;
    keeping the persistence bridge in its own module prevents an older cached UI
    module from breaking every page when persistence helpers are added or changed.
    """
    active_secrets = st.secrets if secrets is None else secrets
    result = bootstrap_cloud_database(DEFAULT_DB_PATH, active_secrets)
    st.session_state[_RESTORE_STATE_KEY] = result
    return result


def show_cloud_database_status(secrets: Mapping[str, Any] | None = None) -> None:
    """Seed cloud storage after SQLite initialization and surface safe notices."""
    active_secrets = st.secrets if secrets is None else secrets
    restore_result = st.session_state.get(_RESTORE_STATE_KEY)
    seed_result = seed_cloud_database_once(DEFAULT_DB_PATH, active_secrets)
    if restore_result and restore_result.configured and not restore_result.ok:
        st.warning(f"云端持久化提示：{restore_result.message} 当前页面仍可使用本地运行缓存。")
    if seed_result.configured and not seed_result.ok:
        st.warning(f"云端持久化提示：{seed_result.message} 请在数据中心检查配置后手动重试。")
    if notice := st.session_state.pop("cloud_persistence_notice", None):
        level, message = notice
        getattr(st, level, st.info)(message)


def cloud_storage_notice() -> None:
    st.caption(
        "Streamlit Community Cloud 的本地 SQLite 仅作为运行缓存；配置 Supabase 后，"
        "系统会在启动时自动恢复，并在关键操作完成后保存一致性云端快照。"
        "SQLite 下载仍可作为离线灾备。"
    )


def persist_cloud_database(reason: str, *, protected: bool = False) -> PersistenceResult:
    result = backup_database_to_cloud(
        DEFAULT_DB_PATH,
        st.secrets,
        reason=reason,
        protected=protected,
    )
    if result.configured:
        if result.ok:
            message = result.message if result.action != "unchanged" else "数据已与云端备份一致。"
            st.session_state["cloud_persistence_notice"] = ("success", message)
        else:
            st.session_state["cloud_persistence_notice"] = ("warning", result.message)
    return result
