# 数据字典

本项目以 SQLite 作为运行缓存。日期均使用 ISO 8601；金额、股价和股息保留数据源币种，港股默认 HKD。

| 表 | 主键 | 用途 |
|---|---|---|
| `security_master` | `symbol` | 标准化代码、名称、行业、板块、证券类型、指数归属与有效期 |
| `daily_prices` | `symbol, trade_date` | 未复权 OHLC、复权收盘、成交量、成交额与更新时间 |
| `dividends` | `symbol, ex_date` | 已除息的每股现金股息、支付日、币种与来源 |
| `corporate_actions` | `symbol, action_date, action_type` | Yahoo 返回的拆股等公司行动记录 |
| `fundamentals` | `symbol, report_period` | 公告日、净利润、经营现金流、现金股息支出、股本与支付率 |
| `monthly_universe` | `month_end, symbol` | 当月是否可用及具体排除原因 |
| `experiment_universe` | `experiment_id, month_end, symbol` | 每轮实验逐月风险过滤结果与排除原因 |
| `monthly_features` | `experiment_id, month_end, symbol` | 每轮实验冻结的因子原值、缩尾值、得分、贡献、总分、覆盖率、下一月收益与质量标记 |
| `forward_returns` | `month_end, symbol` | 因子月与下一有效月末之间的复权价格收益 |
| `rank_ic_monthly` | `experiment_id, month_end` | 实验综合得分的月度Rank IC与滚动均值 |
| `experiment_factor_ic` | `experiment_id, factor` | 实验中各子因子的Rank IC汇总 |
| `backtest_monthly` | `experiment_id, month_end` | 月度组合收益、成本、换手、现金、调仓进出与净值 |
| `backtest_holdings` | `experiment_id, month_end, symbol` | 每月目标权重、实际收益与贡献 |
| `experiments` | `experiment_id` | 手动实验名称、因子模式、权重、风险规则、回测设置、研究指标、状态与正式批准标记 |
| `research_settings` | `setting_key` | 股票池与风险过滤页面保存的规则 |
| `update_logs` | `id` | 请求数量、成功/失败数量及逐股失败原因 |

所有业务表通过主键执行 upsert；重复抓取相同代码与日期会更新，不新增重复行。
