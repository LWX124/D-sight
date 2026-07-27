# 基金套利板块设计（fund_arb）

日期：2026-07-20
状态：已与用户逐节确认

## 1. 目标与范围

为 D-sight 增加"基金套利"板块：**LOF/QDII 折溢价实时监控看板 + agent 查询工具**。

- 参考项目：`/Users/weixi1/Documents/Study/arbTest`（palmmicro/Woody 体系的个人级套利看板）。复用其两项知识资产：88 只基金元数据（`lof_config.yaml`）和估值公式体系（`docs/003`），代码全部按 D-sight 惯例重写。
- 数据源全公开（新浪/东财/akshare/外管局），**不依赖** Woody API、IB Gateway、富途、券商通道等个人基础设施。
- 覆盖全品类（对齐 arbTest TAB）：黄金原油 / QDII欧美 / QDII日本 / QDII亚洲 / 国内LOF / 白银 / 现金管理。
- 不做：交易下单、阈值提醒、用户自选列表、分时走势图、基金池 admin API（首版通过修改 `seed_data/funds.yaml` 重新导入维护）。均为明确砍掉的范围，后续按需加。

### Woody 缺失的补偿：自建校验闭环

Woody 因子本质是"用持仓和历史净值反推的拟合系数"。替代方案三层：

1. **盘后误差对账**：每晚官方净值公布后，回填当日估值误差 `valuation_error`，每只基金形成持续误差序列——估值准确性是可度量的事实。
2. **滚动回归自校准**：近 20 交易日过原点回归 `净值日收益 ≈ β × (标的日收益 × 汇率变动)`，β 即有效仓位，每日盘后更新，替代 Woody position 因子。
3. **误差透明化**：前端展示近 5 日平均绝对误差；R² < 0.6 或误差持续超标的基金打"低置信"标记。

预期精度：指数型 QDII/国内 LOF/白银/债券 ETF 接近 arbTest；黄金原油篮子 LOF 无篮子权重，用跟踪标的近似，误差约 0.3–1%，靠误差列透明化兜底。

## 2. 总体架构

```
backend/app/fund_arb/
├── models.py        # 4 张表
├── schemas.py       # Pydantic 响应模型
├── router.py        # REST API
├── fetchers.py      # 公开数据源抓取（QuoteFetcher 协议 + Fake/Sina/Eastmoney 实现）
├── valuation.py     # 估值公式（纯函数，无 IO）
├── calibration.py   # 滚动回归仓位校准（纯函数）
├── snapshot.py      # 盘中实时快照服务（进程内存缓存）
├── job.py           # 定时任务入口
├── bootstrap.py     # 一次性历史数据回填（上线初始化）
└── seed_data/funds.yaml  # 从 arbTest lof_config.yaml 转换 + 人工校对

backend/app/agent/tools/fund_arb.py   # agent 查询工具
frontend/src/panels/FundArbPanel.tsx  # 看板面板
frontend/src/lib/fundArb.ts           # API client
```

数据流两条线：

- **盘中线**（A 股交易时段每 20 秒）：新浪批量行情（场内价 + 指数 + AG0 + 实时汇率）→ `valuation.py` 重算 → 写进程内存快照 → 前端/agent 读快照。服务端只抓一份，所有用户共享。
- **盘后线**（每日 18:00/20:00/21:30）：东财净值 → 误差对账 → 回归校准 → akshare 申赎状态（每日仅一次）→ 落库。

实时快照不落库（单进程 uvicorn，与 news/social job 的运行假设一致，内存 dict 即可）；只有日频数据进 PostgreSQL。

**快照冷启动**：服务启动时（含非交易时段）snapshot 服务先从 `fund_arb_daily` 每只基金最近一行构造"收盘快照"填充内存，dashboard 永不为空；每行携带 `as_of` 时间，前端据此区分实时/收盘数据。

**历史数据 bootstrap**（`bootstrap.py`，上线时手动跑一次，幂等可重跑）：回填近 60 个交易日的 ① 基金净值历史（东财 lsjz，本身就是历史接口）→ `fund_arb_daily.nav`；② 跟踪标的日收盘（新浪/腾讯日线：指数、美股 ETF、AG0 结算价）→ `fund_arb_tracking_daily`；③ 汇率中间价历史 → 同表。没有这一步，回归校准与 `idx_base` 查询在冷库上无法工作。

**seed 转换校对**（转换脚本 + 人工核对，不可盲搬）：
- arbTest 文档自记的已知 bug：14 只港股 QDII亚洲基金 `related_index` 被错误改写（HSI / 拼错的 HSMCI，应为 HSCI、930914.CSI 等），转换时逐只核对修正。
- 黄金原油篮子基金在 arbTest 中是多资产篮子（依赖 Woody 权重），映射到本设计的单一 `tracking_symbol` 时手工指定近似标的（如 501018→布伦特原油期货），并在配置中保留该品类"近似估值"标记。

## 3. 数据模型（Alembic 迁移一次建 4 张表）

**`fund_arb_funds`** — 基金配置（seed 导入）：
`fund_code`(unique), `fund_name`, `category`(gold_oil/qdii_us_eu/qdii_japan/qdii_asia/domestic_lof/silver/cash_bond), `tracking_symbol`, `tracking_type`(index/future/us_etf), `fx_pair`(USD/HKD/JPY/无), `rate_type`(mid/spot), `valuation_method`(index/silver_future/bond_growth), `pos_ratio_default`, `enabled`。

**`fund_arb_daily`** — 日史宽表（date+fund_code 联合唯一）：
收盘价、涨跌幅、成交额、`nav`、`nav_date`（净值实际日期，显式承载 QDII T-2）、`est_nav_close`、`premium`、`valuation_error`、申购/赎回状态、申购限额。

写入时机：**收盘落库**——snapshot job 在 15:00 后的第一轮把当日收盘快照（价格、`est_nav_close`、`premium`）写入当日行（当日重复触发则 upsert 覆盖），不依赖内存活到 18:00；**盘后精修**——盘后线拿到官方净值后 UPDATE 同一行的 `nav`/`nav_date`/`valuation_error`（对齐 arbTest"动静结合 upsert"思路）。

`valuation_error` 定义：`(est_nav_close − nav_官方) / nav_官方 × 100`，其中两者必须是同一净值日期的值；官方净值未出（QDII 延迟）时留空，待后续盘后线回填。

**`fund_arb_factors`** — 回归因子：`fund_code`+`date`、`position_beta`、`r_squared`、`sample_days`。

**`fund_arb_tracking_daily`** — 跟踪标的日收盘：`date`+`symbol`、`close`。汇率中间价作为特殊 symbol（如 `USDCNY_MID`）也存此表。用途：指数公式基准分母 + 美国假期基准日回溯。

## 4. 数据源与调度

| 数据 | 来源 | 频率 |
|---|---|---|
| 场内价（88 只批量） + 跟踪指数 + AG0 + 在岸汇率 | 新浪 `hq.sinajs.cn`（单请求批量） | 盘中每 20 秒 |
| 美股 ETF 收盘价 | 新浪美股代码（`gb_$xop` 等） | 每日 9:20 + 盘后（美股已收盘，A 股盘中不变，故无需实时订阅） |
| 汇率中间价 | 外管局/chinamoney | 每日 9:20 |
| 基金净值 | 东财 `api.fund.eastmoney.com/f10/lsjz` | 每日 18:00/20:00/21:30（QDII 晚出，三次覆盖） |
| 申赎状态/费率/限额 | akshare `ak.fund_purchase_em()` | 每日仅 1 次（库表打标记防重复，继承 arbTest 纪律） |

fetcher 抽象对齐 `news/sources.py`：`QuoteFetcher` 协议 + `FakeQuoteFetcher`（测试）+ 真实现；单基金失败隔离。

调度挂进现有 `core/scheduler.py`（APScheduler）：

- `fund_arb_snapshot`：Interval 20 秒；job 内判交易时段（工作日 9:25–15:05，`chinese-calendar` 判交易日），非时段直接 return。
- `fund_arb_evening`：Cron 18:00/20:00/21:30（Asia/Shanghai）盘后流水线。
- `fund_arb_morning`：Cron 9:20 汇率中间价 + 美股 ETF 昨收落库。

新增依赖：`chinese-calendar`（arbTest 同款）。

## 5. 估值引擎（`valuation.py` / `calibration.py`，纯函数）

**① 指数公式**（QDII 三类 + 国内 LOF + 黄金原油近似）：

```
est_nav = nav_t1 × (1 + position × (idx_t/idx_base × fx_t/fx_base − 1))
premium = (price / est_nav − 1) × 100
```

- `idx_base` 取与 `nav_date` 同日的标的收盘（查 `fund_arb_tracking_daily`）；当日无价（美国假期）向前回溯到"净值与标的价都存在"的最近交易日；跨度 >5 天（春节）跳过该基金。
- `position` 优先取最新 `position_beta`（R² ≥ 0.6），否则 `pos_ratio_default`。
- 国内 LOF 汇率项恒为 1。

**② 白银**（161226）：`est_nav = nav_t1 × (AG0实时价 / AG0昨结算价)`。不做 VWAP 均价与 COMEX SI 双估值。

**③ 债券/现金**（511880/511360/511520）：`est_nav = nav_latest × (1 + daily_growth × 自然日数)`，`daily_growth` 为近 30 日净值日均增长。不做国债期货方向修正。注意：511880 为交易型货币基金，东财历史净值接口对货基返回的是**每万份收益**而非单位净值，实现时确认口径并折算（或改用累计净值序列），不能直接套公式。

**④ 回归校准**（盘后）：近 20 交易日过原点最小二乘 `position_beta = Σ(r_nav·r_track) / Σ(r_track²)`，R² 一并落库；样本 <10 天不出因子。**分红/拆分防御**：东财 lsjz 的"分红送配"字段标识的除息日样本，以及净值日收益与标的收益异常偏离（|r_nav − r_track| > 5%）的样本，从回归与误差对账中剔除，避免分红跳变污染 β 和误报估值不准。

**防御规则**（继承 arbTest 实盘教训）：

- 溢价只锚最新可得（T-1）净值，禁止用当天净值回填。
- `rate_type=spot` 基金在岸汇率失效时跳过估值，严禁降级用中间价。
- 估值与净值偏离 >50% 回退净值。
- 快照中 >3 分钟未更新的基金标记 stale，不展示旧值假装实时。

## 6. API 与前端

**API**（全部 `get_current_user` 认证）：

- `GET /api/fund-arb/dashboard?category=` — 读内存快照，返回行数据 + 快照时间 + 数据源新鲜度；不传 category 返回全部。
- `GET /api/fund-arb/funds/{code}/history?days=30` — 日史序列（净值/收盘溢价/估值误差）。
- `POST /api/fund-arb/refresh` — 手动触发快照重算（admin only）。

**前端** `FundArbPanel.tsx`：

- `ChatPage.tsx` `PANEL_TITLES` 增加"基金套利"。
- 顶部 TAB 七分类，顺序对齐 arbTest。
- 表格列：代码、名称、现价、涨跌幅、实时估值、实时溢价（默认按溢价绝对值降序）、T-1 净值 + 净值日期（QDII 表头如实标 T-2）、估值误差（近 5 日均值，低置信标黄）、成交额、申购状态（限额标签化）、赎回状态。
- 交易时段 20 秒轮询；非交易时段停止轮询并提示"已收盘，数据为收盘快照"。
- 复用现有组件与 Tailwind 风格，无新前端依赖。

## 7. Agent 工具

`app/agent/tools/fund_arb.py`，工厂模式对齐 `make_news_query`：

- `fund_arb_query(category?, min_premium?, max_premium?, code?)` — 查实时快照，返回结构化文本（含估值误差与申购限额）。
- 挂进 `agent/build.py`；系统提示词补充适用场景。
- 计费走 chat token，工具不单独收费。

## 8. 测试策略

- **估值公式单测**：以 arbTest `docs/003` 数值算例为黄金用例；覆盖假期回溯、spot 失效跳过、50% 偏离回退。
- **回归校准单测**：合成已知 β 序列验证；样本不足回退。
- **fetcher 测试**：respx mock 新浪/东财响应（含畸形响应）。
- **流程测试**：FakeQuoteFetcher → job 一轮 → 断言快照与日史正确。
- **API 测试**：认证与响应结构。
- **前端**：`lib/fundArb.test.ts` + 面板 vitest 渲染测试，对齐 news 面板结构。

## 9. 实施顺序（供 plan 阶段展开）

1. seed 转换脚本（含 related_index 校对与篮子基金标的指定）+ models + Alembic 迁移
2. valuation/calibration 纯函数（TDD，先写公式测试）
3. fetchers + bootstrap 历史回填 + snapshot（含冷启动兜底）+ job
4. router + schemas
5. agent 工具
6. 前端 panel + lib
7. 端到端联调（dev.sh 起全栈 + bootstrap 验证）
