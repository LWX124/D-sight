# A 股数据接口 Spike 结果

日期：2026-07-29
akshare 版本：1.18.64

## 覆盖率

| 字段 | 600519 茅台 | 000001 平安银行 | 300750 宁德时代 | 备注 |
|---|---|---|---|---|
| prices | ✓ | ✓ | ✓ | akshare.stock_zh_a_hist，近 90 日 61 行 |
| financial_metrics | ✓ | ✓ | ✓ | akshare.stock_financial_analysis_indicator，17~18 行 × 86 列 |
| income | ✓ | ✓ | ✓ | akshare.stock_financial_report_sina(利润表)，41~122 行 |
| balance | ✓ | ✓ | ✓ | akshare.stock_financial_report_sina(资产负债表)，39~119 行 |
| cashflow | ✓ | ✓ | ✓ | akshare.stock_financial_report_sina(现金流量表)，41~103 行 |
| company_info | ⚠️ | ⚠️ | ⚠️ | stock_individual_info_em 在 1.18.64 返回 3 列但库内硬赋 2 列崩溃；用替代接口 |

## company_info 替代方案（已验证可用）

| 数据 | 接口 | 字段 | 验证结果 |
|---|---|---|---|
| 公司名 + PE/PB + 市值 | `ak.stock_zh_a_spot_em()` | 名称、市盈率-动态、市净率、总市值、流通市值 | ✓ 含全市场快照，可按代码过滤 |
| 行业 | `ak.stock_board_industry_name_em()` | 板块名称 | ✓ 496 个行业板块 |

`stock_individual_info_em` 的 bug 是 akshare 1.18.64 的已知问题（返回 DataFrame 含 3 列但代码赋 2 列名）。adapter 实现时绕开此函数，用上述两个接口组合获取公司名、PE、PB、市值、行业。

## 关键字段确认

### MarketData 必需字段映射

| MarketData 字段 | A 股数据源 | 列名 | 单位 | 备注 |
|---|---|---|---|---|
| close | stock_zh_a_hist | 收盘 | 元 | 前复权（adjust="qfq"） |
| open | stock_zh_a_hist | 开盘 | 元 | 前复权 |
| high | stock_zh_a_hist | 最高 | 元 | 前复权 |
| low | stock_zh_a_hist | 最低 | 元 | 前复权 |
| volume | stock_zh_a_hist | 成交量 | 股 | |
| amount | stock_zh_a_hist | 成交额 | 元 | |
| pe_ratio | stock_financial_analysis_indicator / spot_em | 市盈率-动态 | 倍 | spot_em 更实时 |
| pb_ratio | stock_financial_analysis_indicator / spot_em | 市净率 | 倍 | spot_em 更实时 |
| roe_ttm | stock_financial_analysis_indicator | 加权净资产收益率 | % | 86 列中含多项 ROE 指标 |
| revenue | stock_financial_report_sina 利润表 | 营业总收入 | 元 | |
| net_income | stock_financial_report_sina 利润表 | 净利润 | 元 | |
| total_assets | stock_financial_report_sina 资产负债表 | 资产总计 | 元 | |
| total_liabilities | stock_financial_report_sina 资产负债表 | 负债合计 | 元 | |
| net_assets | stock_financial_report_sina 资产负债表 | 所有者权益合计 | 元 | |
| cash | stock_financial_report_sina 资产负债表 | 货币资金 | 元 | |
| operating_cf | stock_financial_report_sina 现金流量表 | 经营活动产生的现金流量净额 | 元 | |
| company_name | stock_zh_a_spot_em | 名称 | - | |
| industry | stock_board_industry_name_em | 板块名称 | - | 需反查个股归属行业 |
| total_market_cap | stock_zh_a_spot_em | 总市值 | 元 | |

## 数据量与延迟

- 单标的 prices（90 日）：即时返回
- 单标的 financial_metrics：约 1 秒，86 列（涵盖 PE/PB/ROE/毛利率/负债率等）
- 三表（income/balance/cashflow）：各约 1 秒，40~120 行历史报告期
- 全市场快照 spot_em：约 70 秒（5000+ 标的），需缓存，单标的查询应走个股实时接口

## 缺失/不可用字段

无关键缺失。`stock_individual_info_em` 接口崩溃不影响数据覆盖，已用替代接口验证。

## Go/No-Go

A 股数据：**GO**

五个核心字段（prices/financial_metrics/income/balance/cashflow）三个测试标的全部成功，公司元数据有可靠替代接口。可进入 Phase 2 A 股 adapter 实现。Phase 2 需在 adapter 中封装：
1. stock_individual_info_em 的绕行逻辑（spot_em + board_industry 组合）
2. 三表列名的稳定映射（akshare 财报表列名随版本可能漂移，需契约测试）
3. 前复权参数固定为 qfq
