from __future__ import annotations

from html import escape

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
    "signal_as_of": "信号数据日",
    "latest_price": "最新收盘价（港元）",
    "ma5": "5日均线（港元）",
    "ma20": "20日均线（港元）",
    "return_20d": "近20日涨跌幅",
    "trend_strength": "趋势强弱",
    "reference_ma": "参考均线",
    "reference_price": "参考买点（港元）",
    "reference_low": "观察区间下限（港元）",
    "reference_high": "观察区间上限（港元）",
    "price_vs_reference": "现价相对参考线",
    "entry_guidance": "买点参考说明",
    "price_data_points": "有效价格样本数",
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
    "version_name": "系统版本名称",
    "experiment_note": "实验备注",
    "display_name": "实验显示名称",
    "status": "实验状态",
    "approved": "正式实验",
    "risk_settings_json": "风险过滤设置",
    "backtest_settings_json": "回测设置",
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
    "annualized_return": "年化收益",
    "annualized_volatility": "年化波动",
    "sharpe": "夏普比率",
    "information_ratio": "信息比率",
    "max_drawdown": "最大回撤",
    "calmar": "Calmar比率",
    "average_turnover": "月均换手率",
    "gross_total_return": "扣费前累计收益",
    "net_total_return": "扣费后累计收益",
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


def _html_cell(value: object) -> str:
    if value is None or (not isinstance(value, (list, tuple, dict, set)) and pd.isna(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        value = value.isoformat(sep=" ")
    elif isinstance(value, float):
        value = f"{value:.6g}"
    return escape(str(value), quote=True)


def stable_html_table(frame: pd.DataFrame, max_rows: int = 250) -> str:
    """Render a bounded, escaped HTML table without Streamlit's DataFrame JS bundle."""
    if frame.empty:
        return '<div class="stable-table-empty">暂无记录</div>'

    row_limit = max(1, int(max_rows))
    visible = frame.head(row_limit)
    headers = "".join(f"<th>{escape(str(column), quote=True)}</th>" for column in visible.columns)
    rows = "".join(
        "<tr>" + "".join(f"<td>{_html_cell(value)}</td>" for value in row) + "</tr>"
        for row in visible.itertuples(index=False, name=None)
    )
    note = ""
    if len(frame) > len(visible):
        note = (
            '<div class="stable-table-note">'
            f"当前显示前 {len(visible):,} 行，共 {len(frame):,} 行；完整数据请使用下方 CSV 下载。"
            "</div>"
        )
    return (
        '<div class="stable-table-wrap"><table class="stable-table">'
        f"<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody>"
        f"</table></div>{note}"
    )


def _correlation_color(value: float) -> tuple[str, str]:
    red = (168, 64, 50)
    cream = (246, 241, 231)
    green = (22, 78, 59)
    if pd.isna(value):
        return "#E7EBE8", "#65746D"
    bounded = max(-1.0, min(1.0, float(value)))
    start, end, ratio = (red, cream, bounded + 1.0) if bounded < 0 else (cream, green, bounded)
    rgb = tuple(round(left + (right - left) * ratio) for left, right in zip(start, end))
    luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return "#" + "".join(f"{channel:02X}" for channel in rgb), "#FFFFFF" if luminance < 145 else "#1C2A25"


def stable_correlation_svg(frame: pd.DataFrame, factors: list[str]) -> str:
    """Render a Spearman correlation heatmap without Streamlit's Plotly JS bundle."""
    columns = [column for column in factors if column in frame.columns]
    if not columns:
        return '<div class="stable-table-empty">暂无可计算的因子相关性。</div>'

    correlation = frame[columns].apply(pd.to_numeric, errors="coerce").corr(method="spearman")
    labels = [column_label(column) for column in columns]
    cell_size, left_margin, top_margin, bottom_margin = 58, 190, 128, 44
    width = left_margin + cell_size * len(columns) + 24
    height = top_margin + cell_size * len(columns) + bottom_margin
    elements = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
        'aria-label="因子 Spearman 相关性热力图" xmlns="http://www.w3.org/2000/svg">',
        '<text x="12" y="25" fill="#1C2A25" font-size="16" font-weight="700">因子 Spearman 相关性</text>',
        '<text x="12" y="48" fill="#65746D" font-size="12">-1 为反向，0 为弱相关，+1 为同向</text>',
    ]
    for index, label in enumerate(labels):
        x = left_margin + index * cell_size + cell_size / 2
        y = top_margin - 10
        safe_label = escape(str(label), quote=True)
        elements.append(
            f'<text x="{x:.1f}" y="{y}" fill="#44534D" font-size="11" text-anchor="end" '
            f'transform="rotate(-48 {x:.1f} {y})">{safe_label}</text>'
        )
        row_y = top_margin + index * cell_size + cell_size / 2 + 4
        elements.append(
            f'<text x="{left_margin - 10}" y="{row_y:.1f}" fill="#44534D" font-size="11" '
            f'text-anchor="end">{safe_label}</text>'
        )

    for row_index, row_column in enumerate(columns):
        for column_index, column in enumerate(columns):
            value = correlation.loc[row_column, column]
            fill, text_color = _correlation_color(value)
            x = left_margin + column_index * cell_size
            y = top_margin + row_index * cell_size
            label = "—" if pd.isna(value) else f"{float(value):.2f}"
            elements.append(
                f'<rect x="{x}" y="{y}" width="{cell_size - 2}" height="{cell_size - 2}" '
                f'rx="4" fill="{fill}" />'
            )
            elements.append(
                f'<text x="{x + cell_size / 2:.1f}" y="{y + cell_size / 2 + 4:.1f}" '
                f'fill="{text_color}" font-size="11" font-weight="600" text-anchor="middle">{label}</text>'
            )
    elements.append("</svg>")
    return '<div class="stable-chart-wrap">' + "".join(elements) + "</div>"


def canonicalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    reverse = {label: column for column, label in COLUMN_LABELS.items()}
    cleaned = frame.copy()
    cleaned.columns = [str(column).replace("\ufeff", "").strip() for column in cleaned.columns]
    return cleaned.rename(columns={column: reverse.get(column, column) for column in cleaned.columns})
