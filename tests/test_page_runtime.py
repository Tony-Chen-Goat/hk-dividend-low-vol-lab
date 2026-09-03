from __future__ import annotations

from pathlib import Path

import app.page_runtime as page_runtime


def test_setup_page_wraps_ui_with_cloud_runtime(monkeypatch) -> None:
    events: list[object] = []
    expected = {"price_coverage": 0.75}

    monkeypatch.setattr(page_runtime, "prepare_cloud_database", lambda: events.append("prepare"))
    monkeypatch.setattr(
        page_runtime,
        "_setup_page",
        lambda title, icon: events.append((title, icon)) or expected,
    )
    monkeypatch.setattr(page_runtime, "show_cloud_database_status", lambda: events.append("show"))

    result = page_runtime.setup_page("测试页面", "🧪")

    assert result is expected
    assert events == ["prepare", ("测试页面", "🧪"), "show"]


def test_pages_do_not_import_cloud_helpers_from_cached_ui_module() -> None:
    root = Path(__file__).resolve().parents[1]
    entrypoints = [root / "streamlit_app.py", *sorted((root / "pages").glob("*.py"))]

    for entrypoint in entrypoints:
        source = entrypoint.read_text(encoding="utf-8")
        assert "from app.ui import cloud_storage_notice" not in source
        assert "from app.ui import persist_cloud_database" not in source
        assert "from app.ui import setup_page" not in source
