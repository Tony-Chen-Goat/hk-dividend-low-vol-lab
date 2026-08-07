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
| `monthly_features` | `month_end, symbol` | 13 项原值、缩尾值、得分、贡献、总分、覆盖率与质量标记（JSON 列） |
| `forward_returns` | `month_end, symbol` | 因子月与下一有效月末之间的复权价格收益 |
| `backtest_holdings` | `experiment_id, month_end, symbol` | 每月目标权重、实际收益与贡献 |
| `experiments` | `experiment_id` | 参数、样本窗口、风险约束、样本外指标与得分 |
| `update_logs` | `id` | 请求数量、成功/失败数量及逐股失败原因 |

所有业务表通过主键执行 upsert；重复抓取相同代码与日期会更新，不新增重复行。
