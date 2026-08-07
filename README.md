# 港股红利低波实验室

**HK Dividend Low Volatility Lab** 是一个独立的 Streamlit 港股研究网站，用于真实 Yahoo / CSV / SQLite 数据上的证券池管理、13 因子月末评分、Rank IC、文章方案一基准、港股增强组合、月度回测、滚动样本外调优和实验留档。

## 安装与启动

要求 Python 3.11 或 3.12。

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Streamlit Community Cloud 的主文件固定为 `streamlit_app.py`。项目不需要密钥；Yahoo 只在用户点击“开始更新 Yahoo 数据”后请求，不自动刷新。

## 推荐流程

1. 在“数据中心”上传 `data/sample_hk_universe.csv` 或自定义证券池 CSV。
2. 指定 6–10 年日期范围并手动更新 Yahoo 数据；逐股失败会显示并写入日志。
   同页可更新已实际验证的 Yahoo 基准代码 `^HSI`（恒生指数）和 `^HSCE`（恒生中国企业指数）。两者于 2026-08-06 通过五日请求验证，后续仍可能因 Yahoo 变更而失效。
3. 在“股票池与风险过滤”检查港股主板、证券类型、交易活跃度、价格、派息、成交额和流通市值规则。
4. 在“因子实验室”确认权重合计为 100%，计算并保存月末因子快照。
5. 查看 Rank IC、文章方案一基准和港股 13 因子增强回测。
6. 数据达到至少 6 年后运行滚动样本外参数实验，并在排行榜比较。
7. 下载价格、因子、实验 CSV 和 SQLite 备份。

## 证券池 CSV

必须包含：`symbol,name,sector,security_type,board,index_membership,effective_date,end_date,source`。代码统一为 Yahoo 港股格式，例如 `700`、`0700`、`700.HK` 均转为 `0700.HK`。示例文件仅展示格式，不冒充完整指数成分。

## 数据与存储

价格收益和波动使用复权价格；股息率使用独立现金分红和未复权月末价格，避免重复计入分红。财务值只有在 `published_date` 不晚于因子月末时使用。SQLite 通过主键 upsert 去重。

Streamlit Community Cloud 的本地 SQLite 只是运行缓存，不可视为永久存储。请定期下载数据库备份；应用重启后可在数据中心上传恢复。Yahoo/yfinance 可能限流、改字段或暂时失败，系统不会伪造数据，也不会以演示值替代结果。

## 模型与验证

13 项定义见 [因子定义](docs/FACTOR_DEFINITIONS.md)。Rank IC 是当月全部有效股票得分与下一月复权收益的 Spearman 相关。文章方案一基准与增强模型严格分开；增强结果不是参考文章原始结果。

回测遵循月末信号、下一月持仓与收益对齐。默认前 5 年训练，后续窗口样本外验证；排行榜只按样本外指标。当前成分回溯可能造成幸存者偏差，未来价格、股息、指数成分、退市信息和未公告财务值不得用于过去。

详细说明：

- [数据字典](docs/DATA_DICTIONARY.md)
- [回测方法](docs/BACKTEST_METHODOLOGY.md)
- [数据限制](docs/DATA_LIMITATIONS.md)

## 测试

```bash
pytest -q
```

单元测试使用固定模拟数据，不依赖实时 Yahoo。真实 Yahoo 冒烟测试需另行手动执行；网络失败只应产生数据源警告。部署前还需实际验证计划使用的恒生指数和国企指数 Yahoo 代码。

## 免责声明

本项目仅供研究和教育，不构成投资建议或收益承诺。数据可能不完整、延迟或错误；使用者应核对数据许可、指数历史成分、公告日期、交易成本和监管要求，并独立承担使用风险。
