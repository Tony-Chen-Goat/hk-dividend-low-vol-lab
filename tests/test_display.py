import pandas as pd

from app.display import canonicalize_columns, localized_frame, stable_html_table


def test_localized_and_canonical_column_names_round_trip():
    original = pd.DataFrame({"symbol": ["0005.HK"], "model_score": [88.0], "target_weight": [0.05]})
    localized = localized_frame(original)
    assert list(localized.columns) == ["证券代码", "因子综合得分", "建议目标权重"]
    restored = canonicalize_columns(localized)
    assert list(restored.columns) == list(original.columns)


def test_stable_html_table_escapes_values_and_bounds_rows():
    frame = pd.DataFrame(
        {
            "证券名称": ["<script>alert(1)</script>", "A&B", None],
            "数值": [1.23456789, 2.0, float("nan")],
        }
    )

    rendered = stable_html_table(frame, max_rows=2)

    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "A&amp;B" in rendered
    assert "当前显示前 2 行，共 3 行" in rendered
