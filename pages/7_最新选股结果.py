from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from app.config import DEFAULT_DB_PATH, FACTOR_LABELS, MODEL_FACTOR_WEIGHTS, MODEL_LABELS, RISK_DEFAULTS
from app.display import localized_csv, localized_frame
from app.entry_points import calculate_entry_references
from app.experiment_store import get_experiment, list_experiments
from app.portfolio import build_enhanced_portfolio
from app.research_pipeline import load_feature_panel
from app.stability import read_recent_stock_prices, resolve_stock_data_cutoff
from app.page_runtime import setup_page
from app.ui import empty_state


ENTRY_LABELS = {
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
}


# Display-only labels.  Research data, ranking and exports continue to use the
# original database values; these names are only used by the bilingual board.
STOCK_NAME_ZH = {
    "0001.HK": "长和", "0002.HK": "中电控股", "0003.HK": "香港中华煤气",
    "0005.HK": "汇丰控股", "0006.HK": "电能实业", "0012.HK": "恒基地产",
    "0016.HK": "新鸿基地产", "0027.HK": "银河娱乐", "0066.HK": "港铁公司",
    "0101.HK": "恒隆地产", "0175.HK": "吉利汽车", "0241.HK": "阿里健康",
    "0267.HK": "中信股份", "0285.HK": "比亚迪电子", "0288.HK": "万洲国际",
    "0291.HK": "华润啤酒", "0300.HK": "美的集团", "0316.HK": "东方海外国际",
    "0322.HK": "康师傅控股", "0386.HK": "中国石油化工股份", "0388.HK": "香港交易所",
    "0669.HK": "创科实业", "0688.HK": "中国海外发展", "0700.HK": "腾讯控股",
    "0728.HK": "中国电信", "0762.HK": "中国联通", "0823.HK": "领展房产基金",
    "0836.HK": "华润电力", "0857.HK": "中国石油股份", "0868.HK": "信义玻璃",
    "0883.HK": "中国海洋石油", "0939.HK": "建设银行", "0941.HK": "中国移动",
    "0960.HK": "龙湖集团", "0968.HK": "信义光能", "0981.HK": "中芯国际",
    "0992.HK": "联想集团", "1024.HK": "快手", "1038.HK": "长江基建集团",
    "1044.HK": "恒安国际", "1088.HK": "中国神华", "1093.HK": "石药集团",
    "1099.HK": "国药控股", "1109.HK": "华润置地", "1113.HK": "长实集团",
    "1177.HK": "中国生物制药", "1209.HK": "华润万象生活", "1211.HK": "比亚迪股份",
    "1288.HK": "农业银行", "1299.HK": "友邦保险", "1347.HK": "华虹半导体",
    "1378.HK": "中国宏桥", "1398.HK": "工商银行", "1519.HK": "极兔速递",
    "1658.HK": "邮储银行", "1801.HK": "信达生物", "1810.HK": "小米集团",
    "1876.HK": "百威亚太", "1928.HK": "金沙中国有限公司", "1929.HK": "周大福",
    "1997.HK": "九龙仓置业", "2015.HK": "理想汽车", "2020.HK": "安踏体育",
    "2057.HK": "中通快递", "2269.HK": "药明生物", "2313.HK": "申洲国际",
    "2318.HK": "中国平安", "2319.HK": "蒙牛乳业", "2328.HK": "中国财险",
    "2331.HK": "李宁", "2338.HK": "潍柴动力", "2359.HK": "药明康德",
    "2382.HK": "舜宇光学科技", "2388.HK": "中银香港", "2423.HK": "贝壳",
    "2600.HK": "中国铝业", "2618.HK": "京东物流", "2628.HK": "中国人寿",
    "2688.HK": "新奥能源", "2899.HK": "紫金矿业", "3328.HK": "交通银行",
    "3690.HK": "美团", "3692.HK": "翰森制药", "3750.HK": "宁德时代",
    "3968.HK": "招商银行", "3988.HK": "中国银行", "3993.HK": "洛阳钼业",
    "6160.HK": "百济神州", "6181.HK": "老铺黄金", "6618.HK": "京东健康",
    "6690.HK": "海尔智家", "6862.HK": "海底捞", "9618.HK": "京东集团",
    "9633.HK": "农夫山泉", "9660.HK": "地平线机器人", "9868.HK": "小鹏汽车",
    "9888.HK": "百度集团", "9901.HK": "新东方", "9926.HK": "康方生物",
    "9961.HK": "携程集团", "9987.HK": "百胜中国", "9988.HK": "阿里巴巴",
    "9992.HK": "泡泡玛特", "9999.HK": "网易",
}

SECTOR_ZH = {
    "Financials": "金融",
    "Financial Services": "金融服务",
    "Properties & Construction": "地产建筑",
    "Real Estate": "房地产",
    "Information Technology": "信息科技",
    "Technology": "科技",
    "Telecommunications": "电讯",
    "Communication Services": "通讯服务",
    "Telecommunications and Utilities": "电讯及公用事业",
    "Utilities": "公用事业",
    "Energy": "能源",
    "Industrials": "工业",
    "Basic Materials": "基础材料",
    "Materials": "原材料",
    "Conglomerates": "综合企业",
    "Energy, Materials, Industrials and Conglomerates": "能源、原材料、工业及综合企业",
    "Consumer Discretionary": "非必需消费",
    "Consumer Cyclical": "周期消费",
    "Consumer Defensive": "必需消费",
    "Consumer Discretionary and Consumer Staples": "消费品",
    "Consumer Staples": "必需消费",
    "Healthcare": "医疗保健",
}


BOARD_CSS = """
<style>
  .flight-board { margin:1rem 0 1.35rem; padding:1rem; overflow:hidden; color:#E9F2F0;
    background:radial-gradient(circle at 90% 0,#173A3D 0,transparent 35%),#07171B;
    border:1px solid #27464A; border-radius:14px; box-shadow:0 14px 32px rgba(7,23,27,.18); }
  .flight-board-head { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem;
    padding:.2rem .35rem .9rem; border-bottom:1px solid #315055; }
  .flight-board-kicker { color:#FFB45B; letter-spacing:.19em; font-size:.7rem; font-weight:800; }
  .flight-board-title { margin-top:.25rem; font-size:1.35rem; font-weight:800; letter-spacing:.04em; }
  .flight-board-clock { color:#8FA8A5; text-align:right; font-family:Consolas,monospace; font-size:.76rem; }
  .flight-board-live { display:inline-block; margin-bottom:.3rem; padding:.18rem .5rem; color:#71E5B8;
    border:1px solid #2B7D64; border-radius:999px; letter-spacing:.12em; font-weight:800; }
  .flight-board-scroll { overflow-x:auto; padding-top:.55rem; scrollbar-color:#466267 #10272C; }
  .flight-board-table { width:100%; min-width:1480px; border-collapse:separate; border-spacing:0 4px;
    font-family:"DIN Alternate",Consolas,"Noto Sans SC",sans-serif; font-variant-numeric:tabular-nums; }
  .flight-board-table th { position:sticky; top:0; z-index:2; padding:.52rem .65rem; color:#819B98;
    background:#07171B; font-size:.67rem; letter-spacing:.12em; text-align:left; white-space:nowrap; }
  .flight-board-table td { height:54px; padding:.42rem .65rem; color:#E9F2F0; background:#10262B;
    border-top:1px solid #1D383D; border-bottom:1px solid #1D383D; white-space:nowrap; }
  .flight-board-table tr td:first-child { border-left:3px solid #D68C38; border-radius:6px 0 0 6px; }
  .flight-board-table tr td:last-child { border-radius:0 6px 6px 0; }
  .flight-board-table tbody tr:hover td { background:#163238; }
  .board-rank { color:#FFB45B; font-size:1.1rem; font-weight:900; letter-spacing:.08em; }
  .board-code { color:#71E5B8; font-size:.92rem; font-weight:800; letter-spacing:.06em; }
  .board-number { color:#F0C078; font-weight:800; }
  .board-status { display:inline-block; padding:.22rem .48rem; color:#71E5B8; background:#123A32;
    border:1px solid #285F50; border-radius:4px; font-size:.7rem; }
  .board-bilingual { position:relative; min-width:180px; height:2.45rem; overflow:hidden; }
  .board-sector { min-width:210px; }
  .board-lang { position:absolute; left:0; top:50%; transform:translateY(-50%); width:100%;
    overflow:hidden; text-overflow:ellipsis; font-weight:750; }
  .board-lang-en { color:#B6C7C4; text-transform:uppercase; font-size:.76rem; letter-spacing:.04em; opacity:0; }
  .board-lang-zh { color:#F5F8F7; font-size:.9rem; animation:boardZh 10s ease-in-out infinite; }
  .board-lang-en { animation:boardEn 10s ease-in-out infinite; }
  .board-meter { width:92px; height:4px; margin-top:.28rem; background:#294046; border-radius:9px; overflow:hidden; }
  .board-meter > span { display:block; height:100%; background:#D68C38; border-radius:9px; }
  .board-cycle-note { margin:.65rem .35rem 0; color:#819B98; font-size:.72rem; letter-spacing:.04em; }
  @keyframes boardZh { 0%,42% {opacity:1} 50%,90% {opacity:0} 98%,100% {opacity:1} }
  @keyframes boardEn { 0%,42% {opacity:0} 50%,90% {opacity:1} 98%,100% {opacity:0} }
  @media (prefers-reduced-motion:reduce) { .board-lang-zh {animation:none;opacity:1} .board-lang-en {animation:none;opacity:0} }
</style>
"""


def _stable_html_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<div class="stable-table-empty">暂无可显示记录</div>'
    table = frame.to_html(index=False, escape=True, border=0, classes="stable-table", na_rep="—")
    return f'<div class="stable-table-wrap">{table}</div>'


def _text(value: object, fallback: str = "—") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or fallback


def _bilingual_cell(chinese: str, english: str, *, sector: bool = False) -> str:
    css_class = "board-bilingual board-sector" if sector else "board-bilingual"
    return (
        f'<div class="{css_class}">'
        f'<span class="board-lang board-lang-zh">{escape(chinese, quote=True)}</span>'
        f'<span class="board-lang board-lang-en">{escape(english, quote=True)}</span>'
        "</div>"
    )


def _number(value: object, digits: int = 2) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "—" if pd.isna(numeric) else f"{float(numeric):.{digits}f}"


def _airport_selection_board(
    frame: pd.DataFrame,
    factors: list[str],
    *,
    max_stock_weight: float,
    factor_month: str,
) -> str:
    if frame.empty:
        return '<div class="stable-table-empty">暂无可显示记录</div>'

    fixed_headers = [
        "序号 / NO.", "代码 / CODE", "证券名称 / SECURITY", "所属行业 / SECTOR",
        "综合得分 / SCORE", "覆盖率 / COVERAGE", "目标权重 / WEIGHT", "状态 / STATUS",
    ]
    factor_headers = [FACTOR_LABELS.get(factor, factor) for factor in factors]
    headers = "".join(f"<th>{escape(label, quote=True)}</th>" for label in [*fixed_headers, *factor_headers])
    rows = []
    for _, row in frame.iterrows():
        symbol = _text(row.get("symbol"))
        english_name = _text(row.get("name"), symbol)
        chinese_name = STOCK_NAME_ZH.get(symbol, f"港股 {symbol}")
        english_sector = _text(row.get("sector"), "UNCLASSIFIED")
        chinese_sector = SECTOR_ZH.get(english_sector, "其他行业")
        coverage = pd.to_numeric(pd.Series([row.get("factor_coverage")]), errors="coerce").iloc[0]
        weight = pd.to_numeric(pd.Series([row.get("target_weight")]), errors="coerce").iloc[0]
        coverage_value = 0.0 if pd.isna(coverage) else max(0.0, min(1.0, float(coverage)))
        weight_value = 0.0 if pd.isna(weight) else max(0.0, float(weight))
        weight_meter = min(100.0, weight_value / max(max_stock_weight, 1e-12) * 100)
        constraint = _text(row.get("constraint_note"))
        factor_cells = "".join(
            f'<td class="board-number">{_number(row.get(factor), 3)}</td>' for factor in factors
        )
        rows.append(
            "<tr>"
            f'<td><span class="board-rank">{int(row.get("排名", 0)):02d}</span></td>'
            f'<td><span class="board-code">{escape(symbol, quote=True)}</span></td>'
            f"<td>{_bilingual_cell(chinese_name, english_name)}</td>"
            f"<td>{_bilingual_cell(chinese_sector, english_sector, sector=True)}</td>"
            f'<td><span class="board-number">{_number(row.get("model_score"), 2)}</span></td>'
            f'<td><span class="board-number">{coverage_value:.1%}</span><div class="board-meter"><span style="width:{coverage_value * 100:.1f}%"></span></div></td>'
            f'<td><span class="board-number">{weight_value:.1%}</span><div class="board-meter"><span style="width:{weight_meter:.1f}%"></span></div></td>'
            f'<td><span class="board-status">{escape(constraint, quote=True)}</span></td>'
            f"{factor_cells}</tr>"
        )

    return (
        BOARD_CSS
        + '<section class="flight-board">'
        + '<div class="flight-board-head"><div>'
        + '<div class="flight-board-kicker">HK DIVIDEND LOW VOL · DEPARTURE BOARD</div>'
        + '<div class="flight-board-title">红利低波 · 最新选股信息大屏</div></div>'
        + '<div class="flight-board-clock"><span class="flight-board-live">● LIVE</span><br>'
        + f'FACTOR MONTH　{escape(factor_month, quote=True)}<br>CN / EN AUTO ROTATION</div></div>'
        + '<div class="flight-board-scroll"><table class="flight-board-table"><thead><tr>'
        + headers
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        + '<div class="board-cycle-note">证券名称及行业每 10 秒在中文与英文之间自动循环；向右滚动可查看全部因子字段。</div>'
        + "</section>"
    )


setup_page("最新选股结果", "🔎")
experiments = list_experiments(DEFAULT_DB_PATH)
approved = experiments[experiments["approved"] == 1] if not experiments.empty and "approved" in experiments else pd.DataFrame()
if approved.empty:
    empty_state("尚未批准正式实验。请先完成一轮因子实验、Rank IC和月度组合回测，然后在“实验档案与对比”批准一套实验。")
    st.stop()
experiment_id = str(approved.iloc[0]["experiment_id"])
experiment = get_experiment(experiment_id, DEFAULT_DB_PATH)
model_name = experiment["model_name"]
panel = load_feature_panel(DEFAULT_DB_PATH, model_name, experiment_id, latest_only=True)
if panel.empty:
    empty_state("尚无真实因子结果。请先更新数据并在因子实验室计算。")
    st.stop()
latest_month = panel["month_end"].max()
latest = panel[panel["month_end"] == latest_month].copy()
backtest_settings = experiment.get("backtest_settings") or {}
top_n = int(backtest_settings.get("selected_count") or experiment.get("selected_count") or 10)
max_stock = float(backtest_settings.get("max_stock_weight") or experiment.get("max_stock_weight") or RISK_DEFAULTS["max_stock_weight"])
max_sector = float(backtest_settings.get("max_sector_weight") or experiment.get("max_sector_weight") or RISK_DEFAULTS["max_sector_weight"])
dividend_pct = int(backtest_settings.get("dividend_pct", 50))
inverse_vol_pct = int(backtest_settings.get("inverse_volatility_pct", 50))
st.success(f"正式实验：{experiment['display_name']} · {experiment_id} · {MODEL_LABELS.get(model_name, model_name)}")
st.caption(f"本页只读取已批准实验被冻结设置：每月入选 {top_n} 只，股息率/逆波动率资金配置 {dividend_pct}%/{inverse_vol_pct}%。若要修改，请创建新实验并重新验证后再批准。")
top5_limit = RISK_DEFAULTS["max_top5_weight"]
maximum_invested = min(
    1.0,
    top_n * max_stock,
    top5_limit if top_n <= 5 else top5_limit + (top_n - 5) * max_stock,
)
if maximum_invested < 1:
    st.warning(
        f"按当前入选 {top_n} 只、单股上限 {max_stock:.0%}及前5大权重上限 {top5_limit:.0%}，"
        "即使其他约束全部满足，"
        f"股票仓位最多也只有 {maximum_invested:.0%}，至少会保留 {1 - maximum_invested:.0%} 现金。"
    )
portfolio = build_enhanced_portfolio(
    latest,
    top_n,
    "blend",
    {
        "max_stock_weight": max_stock,
        "max_sector_weight": max_sector,
        "dividend_mix": float(dividend_pct) / 100,
    },
)
portfolio = portfolio.sort_values("model_score", ascending=False).reset_index(drop=True)
portfolio.insert(0, "排名", range(1, len(portfolio) + 1))
entry_symbols = portfolio.loc[portfolio["target_weight"] > 0, "symbol"].head(10).astype(str).tolist()
entry_prices = pd.DataFrame()
if entry_symbols:
    entry_cutoff = resolve_stock_data_cutoff(DEFAULT_DB_PATH, entry_symbols).get("as_of")
    entry_prices = read_recent_stock_prices(
        DEFAULT_DB_PATH, 60, symbols=entry_symbols, as_of=entry_cutoff,
    )
entry_references = calculate_entry_references(portfolio, entry_prices, limit=10)
if not entry_references.empty:
    reference_columns = [column for column in entry_references if column != "symbol"]
    reference_lookup = entry_references.set_index("symbol")
    for column in reference_columns:
        portfolio[column] = portfolio["symbol"].astype(str).map(reference_lookup[column])
st.markdown(f'<span class="oos-tag">因子月末 {latest_month.date().isoformat()}</span>', unsafe_allow_html=True)
cols = st.columns(4)
cols[0].metric("候选股票", len(latest))
cols[1].metric("最终入选", int((portfolio["target_weight"] > 0).sum()))
cols[2].metric("股票权重", f"{portfolio['target_weight'].sum():.1%}")
cols[3].metric("保留现金", f"{portfolio['cash_weight'].sum():.1%}")
board_factors = [factor for factor in MODEL_FACTOR_WEIGHTS[model_name] if factor in portfolio]
st.markdown(
    _airport_selection_board(
        portfolio,
        board_factors,
        max_stock_weight=max_stock,
        factor_month=latest_month.date().isoformat(),
    ),
    unsafe_allow_html=True,
)
st.markdown("#### 前10只入选股票的均线买点参考")
st.info("固定研究规则：5日均线高于20日均线且近20日收益为正时，按短线趋势较强处理并参考5日线；其他情况参考20日线。观察区间为参考均线上下1%。这是一项技术面辅助信息，不是收益预测或自动买入指令。")
if entry_references.empty:
    st.warning("当前入选股票缺少足够的近期价格数据，暂时无法生成均线买点参考。")
else:
    entry_display = portfolio.loc[
        portfolio["symbol"].astype(str).isin(entry_symbols),
        [
            "排名", "symbol", "name", "signal_as_of", "latest_price", "ma5", "ma20",
            "return_20d", "trend_strength", "reference_ma", "reference_price",
            "reference_low", "reference_high", "price_vs_reference", "entry_guidance",
        ],
    ].copy()
    for column in ["latest_price", "ma5", "ma20", "reference_price", "reference_low", "reference_high"]:
        entry_display[column] = pd.to_numeric(entry_display[column], errors="coerce").round(3)
    for column in ["return_20d", "price_vs_reference"]:
        entry_display[column] = pd.to_numeric(entry_display[column], errors="coerce").map(
            lambda value: f"{value:.1%}" if pd.notna(value) else "—"
        )
    entry_display["signal_as_of"] = pd.to_datetime(entry_display["signal_as_of"], errors="coerce").dt.date
    entry_display = localized_frame(entry_display).rename(columns=ENTRY_LABELS)
    st.markdown(_stable_html_table(entry_display), unsafe_allow_html=True)
download_cols = st.columns(2)
download_cols[0].download_button("下载标准字段CSV", portfolio.to_csv(index=False).encode("utf-8-sig"), f"latest_selection_{latest_month.date()}.csv")
download_cols[1].download_button("下载中文字段CSV", localized_csv(portfolio.rename(columns=ENTRY_LABELS)), f"latest_selection_{latest_month.date()}_cn.csv")
st.markdown("#### 人工复核与建仓留档")
st.write("当前名单已经通过该实验的风险过滤，不需要再上传另一份CSV取交集。正式建仓前仍应人工复核最新公告、盈利预警、供股配股、私有化、停牌、派息可持续性和实际成交能力。")
review = portfolio[[column for column in ["symbol", "name", "sector", "model_score", "target_weight", "reference_ma", "reference_price", "entry_guidance"] if column in portfolio]].copy()
review["announcement_review_status"] = "待复核"
review["approved_for_build"] = False
review["manual_target_weight"] = review.get("target_weight", 0.0)
review["manual_note"] = ""
review = st.data_editor(localized_frame(review).rename(columns=ENTRY_LABELS), use_container_width=True, hide_index=True)
st.download_button("下载人工复核建仓清单", review.to_csv(index=False).encode("utf-8-sig"), f"build_review_{experiment_id}_{latest_month.date()}.csv")
st.caption("因子评分权重与资金配置权重相互独立。历史回测表现不是预估收益；缺失数据不会被填成可通过筛选的默认值，约束无法满足时保留现金。")
