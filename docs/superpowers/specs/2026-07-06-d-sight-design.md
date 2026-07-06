# D-sight 设计文档

日期：2026-07-06
状态：已与需求方逐段确认
需求来源：`docs/feature_initial.md`

## 1. 产品定位与范围

AI 投研助手 Web 产品：入口是对话式聊天界面，用户通过自然语言进行股票分析、当日信息总结等；核心分析能力来自预装的 ai-berkshire skill 集（19 个价值投资研究 skill，源码 `/Users/weixi1/Documents/Study/ai-berkshire`）。

- **定位**：小范围真实用户（几十~几百人，朋友/社群），验证产品价值；商业化基建（支付、微信登录）预留接口不实现。
- **部署**：国内云服务器单机（阿里云/腾讯云），域名需 ICP 备案。
- **一期范围**：邮箱登录、聊天 Agent、预装 skill、积分记账、7x24 快讯、知识库（RAG）、skill 市场页。
- **明确不做（一期）**：微信登录（预留 `AuthProvider` 接口）、支付通道（预留 `PaymentProvider`，订阅靠后台/兑换码开通）、社媒信源具体抓取（小红书/微博/公众号/B站，只留架构位）、skill 自定义上传（产品需求即禁止）、**可套利基金分析**（二期以官方 skill 交付——skill 扩展机制天然承接，AkShare 已有可转债/ETF/基金折溢价数据可用；一期用户问到时 agent 用通用搜索+行情工具尽力回答）。

## 2. 总体架构

前后端分离。模块化单体后端 + React SPA 前端。

```
┌─────────────┐        ┌──────────────────────────────────────┐
│ React SPA   │  HTTPS │ FastAPI 单体                          │
│ Vite + TS   │───────▶│ ┌────────┬───────┬────────┬────────┐ │
│ shadcn/ui   │  SSE   │ │ auth   │ chat/ │ skills │ kb     │ │
│ assistant-ui│◀───────│ │ users  │ agent │ market │ (RAG)  │ │
│ TanStack Q  │        │ ├────────┼───────┼────────┼────────┤ │
└─────────────┘        │ │ news   │credits│ llm    │APSched │ │
                       │ │ 7x24   │       │provider│定时任务 │ │
                       │ └────────┴───────┴────────┴────────┘ │
                       └──────┬──────────────┬────────────────┘
                              │              │
                    ┌─────────▼───┐   ┌──────▼──────┐   外部：deepseek API、
                    │ Postgres 16 │   │ Redis 7     │   博查搜索、AkShare、
                    │ + pgvector  │   │ 缓存/限流    │   新浪快讯接口、SMTP、
                    └─────────────┘   └─────────────┘   硅基流动(BGE-M3)
```

**架构形态决策**：模块化单体（方案 A）。几百用户下 agent 任务是 IO 密集，asyncio 单进程可扛；模块内"任务提交/执行/推流"抽象成独立接口，规模上来后可平移为独立 worker（方案 B：arq + Redis pub/sub），微服务（方案 C）排除。

## 3. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 前端框架 | React 18 + Vite + TypeScript | 生态最成熟 |
| UI | shadcn/ui + Tailwind + TanStack Query + Zustand | 与 assistant-ui 同风格体系 |
| 聊天 UI | **assistant-ui**（AssistantTransport runtime） | 2026 年 React 聊天库事实首选；headless primitives 可深度定制；runtime 可换，不绑后端协议 |
| 流协议 | assistant-stream（PyPI，官方 Python 包） | FastAPI 端发协议流，官方有 OSS LangGraph 嵌入式后端示例 |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2 (async) + Alembic | 复用 ai-berkshire Python 工具；async 原生支持 SSE |
| Agent 框架 | **deepagents**（底层 langchain 1.x / LangGraph） | 原生实现 Agent Skills 规范（SKILL.md 渐进披露）、规划 todos、虚拟文件系统、subagents、上下文摘要；LangGraph checkpointer 免费获得会话持久化 |
| 会话持久化 | langgraph-checkpoint-postgres | 崩溃恢复、断点续聊 |
| LLM | langchain-deepseek：`deepseek-v4-flash`（轻量）/ `deepseek-v4-pro`（重型分析） | ⚠️ 旧 ID deepseek-chat/reasoner 于 2026-07-24 退役，禁用；Provider 抽象由 LangChain model 接口天然获得 |
| Embedding | 硅基流动 BGE-M3 API + BGE-reranker | deepseek 无 embedding 接口；中文效果好、免自建 GPU |
| 向量库 | pgvector（HNSW） | 百万级以下向量无需独立向量库 |
| 搜索工具 | 博查 API | 中文财经内容优于海外搜索 API |
| 行情数据 | AkShare | 免费覆盖 A股/港股/美股 |
| 认证 | 邮箱+密码（bcrypt）+ JWT（access 15min / refresh 30d httpOnly cookie） | 微信 OAuth 走同一 `AuthProvider` 接口后续插入 |
| 定时任务 | APScheduler（进程内） | 快讯抓取、积分月度重置 |
| 部署 | Docker Compose + Caddy（自动 HTTPS） | 单机 4C8G 起步 |

**排除项记录**：CopilotKit（侧边栏 copilot 范式不符、锁定深）、Vercel AI SDK（后端重心在 Node）、LangGraph Server / agent-chat-ui（LangGraph Platform 商业授权，且 agent 必须嵌在 FastAPI 内做鉴权/计费）、裸写 LangGraph（重造 deepagents）、自研 agent loop（deepagents 已覆盖且多出 skills/子代理/摘要能力）。

## 4. Agent 运行时与 skill 体系

### 4.1 skill 数据模型

- `skills`：slug、名称、描述、分类、版本、SKILL.md 正文、所需工具列表、模型权重（flash/pro）、积分价格、是否默认安装。
- `skill_files`：附属文件（如 `financial-data.md`、`tools/financial_rigor.py`），文件小直接存库。
- `user_skills`：用户安装关系。注册时自动安装全部官方默认 skill（ai-berkshire 全集）。
- 一次性导入脚本：ai-berkshire 19 个 md 加 YAML frontmatter（name/description）→ 标准 SKILL.md → 入库。

### 4.2 skill 市场

只读列表页 + 详情页 + 安装/卸载。无自定义上传。后台加 skill = 插库记录。

### 4.3 执行流程（一次聊天消息生命周期）

1. 前端 POST `/api/chat/{thread_id}` → JWT 鉴权 → 查用户已安装 skill → 积分余额预检（不足直接拒）。
2. 组装 `create_deep_agent(model=按 skill 元数据的权重字段选 flash/pro（默认 flash，重型研究类 skill 标 pro）, backend=CompositeBackend, skills=[用户已安装 skill 虚拟目录], tools=[web_search, stock_data, kb_search, news_query], checkpointer=Postgres)`。
3. 渐进披露：启动仅注入各 skill 的 name/description；agent 匹配任务后自行 read_file 读入完整 SKILL.md 执行。轻问题一轮直答，重型 skill（如 investment-research）跑长循环（规划 todos + 子 agent + 工具调用）。
4. 全程 assistant-stream 推流：文本增量、工具调用卡片（"正在搜索…"）、todo 进度、子 agent 状态。
5. 结束后记账：基础对话按 token 折积分 + skill 调用固定价，写 `credit_transactions`。

会话管理：assistant-ui ThreadList 提供会话列表；支持新建、重命名、删除（软删，`threads.deleted_at`）；标题默认取首条用户消息截断。

### 4.4 Python 工具执行安全边界

`tools/*.py` 是官方白名单代码（用户不能上传代码），无需重沙箱：deepagents execute 落在资源受限的 `tool-runner` Docker 容器执行，出网仅白名单域名（AkShare 数据源等），单次超时 60s 强杀。

### 4.5 失败处理

- LLM 调用失败：指数退避重试 3 次。
- 工具失败：错误文本返给 agent 自行换路。
- 整体超时 15 分钟强制终止，按已消耗记账，给用户明确失败消息。
- checkpointer 保证刷新/断线不丢已生成内容。

### 4.6 PoC 门禁与降级预案（实施第 0 步）

用 deepagents + deepseek-v4-pro 跑 investment-research 全流程，用 10 个代表性问题的手工评估集验收（工具调用服从性、步骤完整性、数据交叉验证是否执行）。不达标则重型 skill 降级为固定 LangGraph 图（步骤编排写死，LLM 只做步内推理），轻量 skill 维持 deepagents 自由循环。deepagents 版本锁定。

## 5. 知识库（RAG）

- **模型**：`kb`（名称、owner、是否共享、共享 slug）、`kb_documents`（状态 pending/processing/ready/failed）、`kb_chunks`（切片 + BGE-M3 向量，HNSW 索引）、`kb_subscriptions`（共享订阅，只读引用不复制）。
- **入库管道**（异步，前端轮询状态）：上传（PDF/Word/Markdown/TXT，≤20MB）→ PyMuPDF / python-docx 提取 → 标题结构 + 512 token 滑窗切片 → BGE-M3 批量向量化 → 入库。单文档失败标 failed 附原因，不阻塞。
- **检索**：`kb_search` 作为 agent 工具。用户在聊天中选择挂载的知识库（自有 + 已订阅共享），agent 决定何时检索。向量 top-20 → BGE-reranker 重排 top-5 → 带出处返回。不做独立问答页，聊天是唯一入口。
- **共享**：详情页生成共享链接（随机 slug）→ 他人订阅；owner 可关闭共享，订阅引用随之失效。一期只有只读全库共享，无细粒度权限。

## 6. 新闻热点

- **(1) 7x24 快讯**：APScheduler 每 5 分钟抓新浪财经接口（接口后续提供：`NewsSource` 抽象基类 + `SinaLiveSource` 占位实现，地址/解析配置化）→ 去重（外部 ID + 内容 hash）→ `news_items`。前端快讯流：倒序无限滚动 + 30s 轮询增量（不上 WebSocket）。
- **(2) 其他信源**：`news_sources` 表（名称、类型、配置 JSON、启用、频率），新信源 = 插记录 + 写 Source 子类。
- **(3) 社媒**（小红书/微博/公众号/B站）：一期仅架构预留——`channel` 字段区分 news/social，前端按 channel 分 tab；不写具体抓取代码，后续逐渠道攻坚。
- **与 Agent 打通**：`news_query` 工具（按时间/关键词查快讯库），支撑"当日最新信息总结"需求。

## 7. 账号与积分/订阅

### 7.1 认证

- 邮箱注册：6 位验证码邮件（阿里云邮件推送 SMTP），bcrypt 存密码。
- JWT：access 15 分钟 + refresh 30 天（httpOnly cookie，可吊销）。
- 扩展性：`user_identities` 表将登录方式与账号解耦（一账号多登录方式），`AuthProvider` 接口预留微信 OAuth；`users` 预留 `wechat_openid/unionid` 可空列。

### 7.2 积分

- `credit_accounts`（余额、月度配额、重置日）+ `credit_transactions`（类型、数额、关联对象、余额快照）。余额由流水推导可审计；一切变更走记账函数（单事务 + 行锁防并发双扣）。
- 免费 100 分/月，订阅 2000 分/月；月初重置为"清零再发"非累加（统一北京时间，APScheduler 零点任务）。
- 扣费：基础对话按 token 折算（参数可配），skill 调用按定价固定扣；执行前预检、执行后实扣、失败按实际消耗扣。
- 订阅开通：一期后台管理接口 + 兑换码（手动收款）；`PaymentProvider` 抽象预留微信支付。

### 7.3 管理后台（一期最小化）

不做管理 UI。`users.role`（user/admin）+ 一组 admin 角色保护的 API 与命令行脚本，覆盖四类操作：skill 上架/下架、信源增改与启停、兑换码生成、订阅/积分手动调整。所有 admin 操作写审计日志（复用 `credit_transactions` 模式，操作类流水表 `admin_audit_log`）。

## 8. 数据模型总览

`users`、`user_identities`、`skills`、`skill_files`、`user_skills`、`threads`（LangGraph checkpoint 表由框架自管）、`kb`、`kb_documents`、`kb_chunks`、`kb_subscriptions`、`news_sources`、`news_items`、`credit_accounts`、`credit_transactions`、`subscriptions`、`admin_audit_log`

## 9. 部署与测试

- **部署**：Docker Compose 五容器：`caddy`（HTTPS/静态前端/反代）、`api`（FastAPI + deepagents + APScheduler）、`tool-runner`（工具执行容器）、`postgres:16`（pgvector）、`redis:7`。配置走环境变量，密钥不进 git。
- **后端测试**：pytest + pytest-asyncio；积分记账/鉴权/skill 安装/RAG 管道做单元+集成（testcontainers 真 Postgres）；agent 链路 mock LLM 做协议级测试（工具调用序列、流事件格式）；真 LLM 质量靠 PoC 手工评估集。
- **前端测试**：vitest 组件测试 + Playwright 冒烟（注册→登录→发消息→流式回复）。
- **CI**：GitHub Actions，PR 跑 lint + test。

## 10. 实施顺序

1. **PoC（门禁）**：deepagents + deepseek-v4 跑通 investment-research，质量验收，决定是否启用降级预案。
2. 骨架：项目脚手架、auth、聊天链路（assistant-ui ⟷ assistant-stream ⟷ deepagents）。
3. skill 体系 + 积分记账。
4. 知识库（上传/RAG/共享）。
5. 新闻热点（NewsSource 框架 + 快讯流页）。
6. skill 市场页 + 打磨、部署上线。

## 11. 主要风险

| 风险 | 应对 |
|---|---|
| deepseek 跑 deepagents 长循环服从性不足（harness 为 Claude 调优） | PoC 门禁 + 固定图降级预案（见 4.6） |
| deepagents API 迭代快 | 锁版本，升级走显式评估 |
| 旧模型 ID 2026-07-24 退役 | 直接使用 deepseek-v4-flash / v4-pro |
| 新浪接口未定 | NewsSource 抽象 + 占位实现，接口到位仅改配置/解析 |
| 长任务成本失控 | 积分预检 + 15 分钟超时 + 按 skill 定价 |
