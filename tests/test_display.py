import pandas as pd

from app.display import canonicalize_columns, localized_frame


def test_localized_and_canonical_column_names_round_trip():
    original = pd.DataFrame({"symbol": ["0005.HK"], "model_score": [88.0], "target_weight": [0.05]})
    localized = localized_frame(original)
    assert list(localized.columns) == ["证券代码", "因子综合得分", "建议目标权重"]
    restored = canonicalize_columns(localized)
    assert list(restored.columns) == list(original.columns)
