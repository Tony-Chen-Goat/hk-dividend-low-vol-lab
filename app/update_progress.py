from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def update_progress_metrics(
    state: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Normalize persisted Yahoo update state for consistent cross-page display."""
    state = state or {}
    total = max(0, _integer(state.get("requested_count")))
    completed = max(0, _integer(state.get("completed_count")))
    if total:
        completed = min(completed, total)
    fraction = completed / total if total else 0.0

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    started = _timestamp(state.get("started_at"))
    updated = _timestamp(state.get("updated_at")) or started

    elapsed_seconds = max(0.0, (current_time - started).total_seconds()) if started else 0.0
    if state.get("status") != "running":
        try:
            elapsed_seconds = max(0.0, float(state.get("elapsed_seconds", elapsed_seconds)))
        except (TypeError, ValueError):
            pass

    eta_seconds: float | None = None
    if state.get("status") == "running" and completed > 0 and total > completed and elapsed_seconds > 0:
        eta_seconds = elapsed_seconds * (total - completed) / completed
    elif total and completed >= total:
        eta_seconds = 0.0

    return {
        "status": str(state.get("status") or "unknown"),
        "phase": str(state.get("phase") or "正在获取 Yahoo 市场数据"),
        "total": total,
        "completed": completed,
        "remaining": max(0, total - completed),
        "fraction": min(1.0, max(0.0, fraction)),
        "percent": min(100.0, max(0.0, fraction * 100)),
        "elapsed_seconds": elapsed_seconds,
        "eta_seconds": eta_seconds,
        "current_symbol": str(state.get("current_symbol") or ""),
        "seconds_since_update": max(0.0, (current_time - updated).total_seconds()) if updated else None,
    }


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "估算中"
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}小时{minutes}分钟"
    if minutes:
        return f"{minutes}分钟{secs}秒"
    return f"{secs}秒"
