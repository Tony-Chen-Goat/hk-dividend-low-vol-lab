from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app.universe import validate_universe_csv


PROJECT_ROOT = Path(__file__).parents[1]
PAGE_FILES = [PROJECT_ROOT / "streamlit_app.py", *sorted((PROJECT_ROOT / "pages").glob("*.py"))]


@pytest.mark.parametrize("page_path", PAGE_FILES, ids=lambda path: path.name)
def test_every_page_renders_without_python_exception(page_path: Path):
    app = AppTest.from_file(str(page_path)).run(timeout=45)
    errors = [str(item.value) for item in app.exception]
    assert errors == []


def test_builtin_demo_universe_is_valid_and_complete():
    path = PROJECT_ROOT / "data" / "current_hsi_hscei_universe.csv"
    frame = pd.read_csv(path, dtype={"symbol": str})
    validated = validate_universe_csv(frame)

    assert len(validated) == 102
    assert validated["symbol"].nunique() == 102
    assert validated["symbol_error"].isna().all()
    assert frame["index_membership"].str.contains("HSI").sum() == 93
    assert frame["index_membership"].str.contains("HSCEI").sum() == 50


def test_demo_pages_do_not_use_lazy_slider_component():
    page_source = "\n".join(path.read_text(encoding="utf-8") for path in PAGE_FILES)
    assert ".slider(" not in page_source


def test_risk_page_avoids_unstable_dataframe_frontend_bundle():
    source = (PROJECT_ROOT / "pages" / "2_股票池与风险过滤.py").read_text(encoding="utf-8")

    assert ".dataframe(" not in source
    assert "_stable_html_table" in source
    assert "from app.display import localized_csv, localized_frame, stable_html_table" not in source
