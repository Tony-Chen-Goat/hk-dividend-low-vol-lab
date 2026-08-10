import pandas as pd

from app.final_pool import build_final_candidate_pool


def test_final_pool_requires_risk_membership_weight_coverage_and_constraints():
    risk = pd.DataFrame({
        "symbol": ["0005.HK", "0941.HK", "0003.HK"],
        "name": ["A", "B", "C"],
    })
    selection = pd.DataFrame({
        "symbol": ["0005.HK", "0941.HK", "0003.HK", "9988.HK"],
        "target_weight": [0.05, 0.0, 0.04, 0.03],
        "factor_coverage": [1.0, 1.0, 0.9, 1.0],
        "constraint_note": ["满足约束", "满足约束", "满足约束", "满足约束"],
        "model_score": [90, 80, 70, 60],
    })
    final, excluded = build_final_candidate_pool(risk, selection)
    assert final["symbol"].tolist() == ["0005.HK"]
    reasons = "；".join(excluded["final_exclusion_reasons"].dropna())
    assert "建议目标权重为零" in reasons
    assert "因子数据覆盖率不足100%" in reasons
    assert "未通过或未出现在风险过滤入选池" in reasons


def test_final_pool_accepts_chinese_column_titles_and_percentages():
    risk = pd.DataFrame({"证券代码": ["5"], "证券名称": ["汇丰"]})
    selection = pd.DataFrame({
        "证券代码": ["0005.HK"],
        "建议目标权重": ["5%"],
        "因子数据覆盖率": ["100%"],
        "组合约束状态": ["满足约束"],
    })
    final, excluded = build_final_candidate_pool(risk, selection)
    assert final.loc[0, "symbol"] == "0005.HK"
    assert final.loc[0, "target_weight"] == 0.05
    assert excluded.empty
