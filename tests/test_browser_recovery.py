from __future__ import annotations

from pathlib import Path


def test_sidebar_exposes_fresh_session_recovery_link() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "ui.py").read_text(encoding="utf-8")

    assert "?reload=" in source
    assert "重新加载最新版本" in source
