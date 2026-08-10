from __future__ import annotations

import pandas as pd

from .display import canonicalize_columns
from .yahoo_provider import normalize_hk_symbol


def _numeric(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    is_percent = text.str.endswith("%")
    numeric = pd.to_numeric(text.str.rstrip("%"), errors="coerce").astype(float)
    numeric.loc[is_percent] = numeric.loc[is_percent] / 100
    return numeric


def _normalize_symbols(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    normalized, errors = [], []
    for value in data["symbol"]:
        try:
            normalized.append(normalize_hk_symbol(value))
            errors.append(None)
        except (TypeError, ValueError) as exc:
            normalized.append(None)
            errors.append(str(exc))
    data["symbol"] = normalized
    data["symbol_validation_error"] = errors
    return data


def build_final_candidate_pool(
    risk_universe: pd.DataFrame,
    latest_selection: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    risk = canonicalize_columns(risk_universe)
    selection = canonicalize_columns(latest_selection)
    if "symbol" not in risk:
        raise ValueError("风险过滤CSV缺少 symbol（证券代码）列。")
    required = {"symbol", "target_weight", "factor_coverage"}
    if missing := required - set(selection.columns):
        raise ValueError(f"最新选股CSV缺少列: {', '.join(sorted(missing))}")

    risk = _normalize_symbols(risk)
    selection = _normalize_symbols(selection)
    risk = risk.drop_duplicates("symbol", keep="last")
    selection = selection.drop_duplicates("symbol", keep="first")
    selection["target_weight"] = _numeric(selection["target_weight"])
    selection["factor_coverage"] = _numeric(selection["factor_coverage"])

    risk_symbols = set(risk.loc[risk["symbol_validation_error"].isna(), "symbol"].dropna())
    reasons = []
    for row in selection.to_dict("records"):
        current = []
        if row.get("symbol_validation_error"):
            current.append("证券代码格式无效")
        elif row.get("symbol") not in risk_symbols:
            current.append("未通过或未出现在风险过滤入选池")
        if pd.isna(row.get("target_weight")) or row.get("target_weight", 0) <= 0:
            current.append("建议目标权重为零或缺失")
        if pd.isna(row.get("factor_coverage")) or row.get("factor_coverage", 0) < 0.999999:
            current.append("因子数据覆盖率不足100%")
        note = str(row.get("constraint_note", "")).strip()
        if note and note != "满足约束":
            current.append(f"组合约束状态：{note}")
        reasons.append("；".join(current))
    selection["final_exclusion_reasons"] = reasons

    eligible = selection[selection["final_exclusion_reasons"].eq("")].copy()
    risk_details = risk.drop(columns=["symbol_validation_error"], errors="ignore")
    final = eligible.merge(risk_details, on="symbol", how="inner", suffixes=("", "_risk"))
    for column in ["name", "sector"]:
        risk_column = f"{column}_risk"
        if risk_column in final:
            if column not in final:
                final[column] = final[risk_column]
            else:
                final[column] = final[column].fillna(final[risk_column])
    final = final.drop(columns=[column for column in final if column.endswith("_risk")], errors="ignore")
    final = final.drop(columns=["symbol_validation_error", "final_exclusion_reasons"], errors="ignore")
    final = final.sort_values(["model_score", "target_weight"], ascending=False, na_position="last") if "model_score" in final else final.sort_values("target_weight", ascending=False)

    excluded = selection[selection["final_exclusion_reasons"].ne("")].copy()
    selected_symbols = set(selection["symbol"].dropna())
    risk_only = risk[~risk["symbol"].isin(selected_symbols)].copy()
    if not risk_only.empty:
        risk_only["final_exclusion_reasons"] = "未进入最新因子精选名单"
        excluded = pd.concat([excluded, risk_only], ignore_index=True, sort=False)
    return final.reset_index(drop=True), excluded.reset_index(drop=True)
