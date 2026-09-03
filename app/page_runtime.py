from __future__ import annotations

from .cloud_ui import prepare_cloud_database, show_cloud_database_status
from .ui import setup_page as _setup_page


def setup_page(title: str, icon: str = "📊") -> dict:
    """Set up a page with cloud restore before, and cloud status after, SQLite init."""
    prepare_cloud_database()
    snapshot = _setup_page(title, icon)
    show_cloud_database_status()
    return snapshot
