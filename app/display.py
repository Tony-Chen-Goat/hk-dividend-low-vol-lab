from __future__ import annotations

import pandas as pd

from .config import FACTOR_LABELS


COLUMN_LABELS = {
    "symbol": "证券代码",
    "raw_symbol": "原始证券代码",
    "symbol_error": "代码校验错误",
    "name": "证券名称",
    "sector": "所属行业",
    "security_type": "证券类型",
    "board": "上市板块",
    "index_membership": "指数归属",
    "effective_date": "生效日期",
    "end_date": "结束日期",
    "source": "数据来源",
    "listing_date": "上市日期",
    "listing_days": "上市交易日数",
    "trade_date": "交易日期",
    "month_end": "因子月末",
    "next_month_end": "下一月末",
    "close": "收盘价",
    "adjusted_close": "复权收盘价",
    "volume": "成交量",
    "avg_traded_value_20d": "20日平均成交额",
    "valid_trading_ratio_60d": "60日有效交易比例",
    "max_suspension_days": "最长连续停牌日",
    "free_float_market_cap": "自由流通市值",
    "included": "是否通过风险过滤",
    "exclusion_reasons": "排除原因",
    "model_name": "因子模式",
    "model_score": "因子综合得分",
    "factor_coverage": "因子数据覆盖率",
    "coverage": "数据覆盖率",
    "quality_flag": "数据质量标记",
    "forward_return": "下一月收益率",
    "rank_ic": "月度Rank IC",
    "cumulative_rank_ic": "累计Rank IC",
    "rolling_12m_ic": "滚动12月平均IC",
    "valid_count": "有效股票数量",
    "skip_reason": "跳过原因",
    "factor": "因子",
    "mean_rank_ic": "平均Rank IC",
    "rank_ic_std": "Rank IC标准差",
    "positive_ratio": "IC正值比例",
    "rank_icir": "Rank ICIR",
    "annualized_rank_icir": "年化ICIR",
    "latest_12m_rank_ic": "最近12月平均IC",
    "gross_return": "扣费前组合收益",
    "transaction_cost": "交易成本",
    "net_return": "扣费后组合收益",
    "turnover": "组合换手率",
    "cash_weight": "保留现金比例",
    "net_value": "扣费后净值",
    "gross_value": "扣费前净值",
    "drawdown": "组合回撤",
    "target_weight": "建议目标权重",
    "raw_weight": "约束前权重",
    "constraint_note": "组合约束状态",
    "contribution": "收益贡献",
    "period": "月份",
    "ranking": "排名",
    "排名": "排名",
    "reason": "失败原因",
    "symbol_validation_error": "证券代码校验错误",
    "final_exclusion_reasons": "未进入最终池原因",
    "approved_for_build": "批准进入候选池",
    "announcement_review_status": "公告复核状态",
    "manual_target_weight": "人工计划权重",
    "manual_note": "人工备注",
    "experiment_id": "实验编号",
    "created_at": "创建时间",
    "universe_name": "证券池名称",
    "data_start": "数据开始日期",
    "data_end": "数据结束日期",
    "train_window": "训练窗口",
    "validation_window": "验证窗口",
    "factor_weights_json": "因子权重",
    "group_weights_json": "因子组权重",
    "portfolio_method": "组合配置方式",
    "selected_count": "入选数量",
    "entered_count": "新进入数量",
    "exited_count": "退出数量",
    "entered_symbols": "本月新进入",
    "exited_symbols": "本月退出",
    "retained_symbols": "继续持有",
    "rebalance_action": "调仓动作",
    "max_stock_weight": "单股上限",
    "max_sector_weight": "单行业上限",
    "metrics_json": "实验指标",
    "score": "实验综合得分",
    "survivor_bias": "存在幸存者偏差",
    "quality_note": "数据质量说明",
    "is_out_of_sample": "是否样本外",
}
COLUMN_LABELS.update(FACTOR_LABELS)


def column_label(column: str) -> str:
    if column in COLUMN_LABELS:
        return COLUMN_LABELS[column]
    if column.endswith("__score"):
        factor = column.removesuffix("__score")
        return f"{FACTOR_LABELS.get(factor, factor)}得分"
    if column.endswith("__winsorized"):
        factor = column.removesuffix("__winsorized")
        return f"{FACTOR_LABELS.get(factor, factor)}缩尾值"
    if column.endswith("__contribution"):
        factor = column.removesuffix("__contribution")
        return f"{FACTOR_LABELS.get(factor, factor)}贡献"
    if column.endswith("_return") and column not in COLUMN_LABELS:
        return column.replace("_return", "收益率")
    if column.endswith("_value") and column not in COLUMN_LABELS:
        return column.replace("_value", "净值")
    return column


def localized_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(columns={column: column_label(str(column)) for column in frame.columns})


def localized_csv(frame: pd.DataFrame) -> bytes:
    return localized_frame(frame).to_csv(index=False).encode("utf-8-sig")


def canonicalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    reverse = {label: column for column, label in COLUMN_LABELS.items()}
    cleaned = frame.copy()
    cleaned.columns = [str(column).replace("\ufeff", "").strip() for column in cleaned.columns]
    return cleaned.rename(columns={column: reverse.get(column, column) for column in cleaned.columns})
