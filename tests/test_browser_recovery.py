from __future__ import annotations

from pathlib import Path


def test_sidebar_exposes_fresh_session_recovery_link() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "ui.py").read_text(encoding="utf-8")

    assert "?reload=" in source
    assert "重新加载最新版本" in source


def test_stale_component_chunks_trigger_one_bounded_cache_bust() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "ui.py").read_text(encoding="utf-8")

    assert "COMPONENT_RECOVERY_SCRIPT" in source
    assert "Failed to fetch dynamically imported module" in source
    assert "window.__hkLowVolRecoveryInstalled" in source
    assert "sessionStorage.getItem(recoveryKey)" in source
    assert "now - previous < 45000" in source
    assert 'url.searchParams.set("reload", String(now))' in source
    assert "unsafe_allow_javascript=True" in source


def test_custom_html_uses_dedicated_renderer_instead_of_markdown() -> None:
    root = Path(__file__).resolve().parents[1]
    application_files = [root / "streamlit_app.py", *sorted((root / "pages").glob("*.py"))]

    assert "def render_html" in (root / "app" / "ui.py").read_text(encoding="utf-8")
    for path in application_files:
        assert "unsafe_allow_html=True" not in path.read_text(encoding="utf-8"), path.name
