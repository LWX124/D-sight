# 知识库内容源接入设计

**日期**: 2026-08-02
**状态**: 待实现

## 背景

`app/kb/` 已具备完整的向量检索能力：`Kb` / `KbDocument` / `KbChunk` 三表 + pgvector，
上传 txt/md/pdf 后台切片入库，`kb_search` agent 工具，聊天面板的 `KbMountSelector` 挂载。

缺的是内容来源：知识库只能吃手动上传的文件，平台自己抓来的公众号文章和 7x24 快讯
进不去。`KbDocument` 只有 `filename` 一个标识字段，没有来源概念，也没有任何去重键。
前端 `KbPanel` 是卡片网格，无法浏览库内内容。

## 目标

- 社媒信息（当前为微信公众号）支持单篇加入知识库，也支持整号持续订阅入库
- 7x24 快讯支持批量加入知识库
- 内容来源可扩展：未来接入新平台只需实现一个 resolver，入库路径不变
- 避免重复：同一内容在同一知识库只存一份；相同文本不重复调用 embedding API
- 知识库面板支持「库列表 → 内容索引 → 详情」三级浏览，外加可折叠的对话栏
- 可对单个知识库直接对话；现有聊天面板的挂载机制保持不变

## 非目标

- 历史文章回溯抓取（翻页拉取该号的历史列表）。仅覆盖 `wechat_articles` 里已有的
  文章及此后 poll 到的新文章
- 信源级订阅快讯（整个 sina_live 持续入库）
- `SocialPanel` 底部「向 AI 提问当前文章」占位框的实现
- 全局跨知识库的内容去重（见「关键决策」）

## 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 整号加入的语义 | **持续订阅**，非一次性快照 | `poll_all_subscriptions()` 已在 scheduler 里跑，有现成挂钩点 |
| 去重层次 | **文档级幂等 + 向量复用**，不做全局内容去重 | 重复的真实成本在 embedding API 调用，不在 Postgres 多存一份文本；全局去重会把 `kb_chunks` 的 `WHERE kb_id IN (...)` 改成 join，权限模型跟着复杂化，不划算 |
| 抓取范围 | **不回溯历史** | 正文懒抓走共享凭证池 + 微信风控，已是链路最脆一环；整号入库把它从「点一篇拉一次」放大成「批量拉 N 次」，再叠加历史翻页是两个风险相乘 |
| 快讯粒度 | **单条 = 一个文档** | 合并成一个文档会把不相关内容焊进同一个 chunk，rerank 救不回来 |
| 单库对话的后端路径 | **与现有聊天完全相同**，仅前端锁定挂载集合 | 「把整库塞进上下文」在文档变多后必爆；且会让同一个库在两处表现不一致 |
| 成本控制 | **硬上限**，`role="admin"` 豁免 | 扣积分会让后台任务在用户不在场时消耗对话额度，这种看不见的扣费体验很差 |
| 取消订阅 | **保留已入库文档** | 知识库语义是「我攒下来的资料」，不该因退订而蒸发；清理走显式的 `purge` 操作 |

## 数据模型

### 扩展 `kb_documents`

```python
title:         str            # 显示名。上传=文件名，公众号=文章标题，快讯=快讯标题
filename:      str | None     # 改为可空，仅上传文档有值
source_type:   str            # "upload" | "wechat_article" | "news_item"
source_ref_id: str | None     # 源表主键；upload 为 NULL
source_url:    str | None     # 原文链接
published_at:  datetime|None  # 原始发布时间，索引列表按它倒序
kb_source_id:  uuid | None    # 由整号订阅自动入库时指向 kb_sources

UniqueConstraint(kb_id, source_type, source_ref_id)
```

唯一约束利用 Postgres「NULL 互不相等」的性质：上传文档 `source_ref_id` 为 NULL，
不受约束影响，同名文件仍可重复上传。未来接入新平台只需扩 `source_type` 的取值。

迁移需回填 `title = filename`，然后把 `filename` 改为 nullable。

### 新表 `kb_sources`

```python
id
kb_id          → kb.id CASCADE
source_type:   str       # "wechat_account"（未来 "xhs_user" 等）
source_ref_id: str       # WechatAccount.id
display_name:  str       # 号名，冗余存一份免 join
status:        str       # pending / syncing / ready / failed / limited
enabled:       bool
last_synced_at, created_at

UniqueConstraint(kb_id, source_type, source_ref_id)
```

### 扩展 `kb_chunks`（向量复用）

```python
content_hash:    str(64)   # sha256(chunk 文本)，建索引
embedding_model: str       # 建索引
```

入库前先查：

```sql
SELECT embedding FROM kb_chunks
WHERE content_hash = :h AND embedding_model = :m LIMIT 1
```

命中则复用，未命中才调 SiliconFlow。**不建独立缓存表**——复用 `kb_chunks` 意味着
不需要清理策略：最后一个引用该文本的 chunk 被删时「缓存」自动消失。换 embedding
模型时靠 `embedding_model` 列自然失效，不会拿旧模型的向量污染新索引。

存储上文本副本仍各存一份（几 KB 的事），省下的是花钱的 API 调用。

### 扩展 `threads`

```python
ref_id: uuid | None   # type="kb" 时指向 kb.id
```

沿用新闻助手那套：`type` 非 `"chat"` 的会话不进左侧全局会话列表
（见 `threads/router.py` 的 `list_threads`）。

## 统一入库管线

把「内容从哪来」和「怎么入库」切开，新平台只需实现一个 resolver。

### 中间表示（`app/kb/sources.py`）

```python
@dataclass
class SourceItem:
    source_type: str          # "wechat_article" / "news_item" / ...
    source_ref_id: str
    title: str
    text: str                 # 已就绪的纯文本正文
    source_url: str | None
    published_at: datetime | None

async def resolve_wechat_article(db, article_id, http) -> SourceItem   # 正文缺失时补拉
async def resolve_news_item(db, item_id) -> SourceItem                 # 直接读，无外部请求
```

`title` 的取值：公众号用 `WechatArticle.title`；快讯的 `NewsItem.title` 可空，为空时
取 `content` 前 40 字加省略号。`text` 为空或纯空白时不建文档，直接返回错误
（手动加入）或跳过（订阅回填）——空文档切不出 chunk，进库只会污染索引。

### 入库入口

```python
async def add_source_item(db, kb_id, item, kb_source_id=None) -> Literal["added", "duplicate"]
```

先按 `(kb_id, source_type, source_ref_id)` 查重，命中返回 `duplicate`（不是错误，
前端提示「已在库中」）；否则建 `KbDocument(status="pending")` 并把切片任务丢后台。
并发插入靠唯一约束兜底：捕 `IntegrityError` 转成 `duplicate`，不依赖「先查后插」
——那中间有竞态窗口。

### 切片任务重构

现有 `ingest_document(doc_id, filename, raw)` 把「解析文件」和「切片+向量化」揉在
一起。拆成：

```python
async def ingest_text(document_id, text)                # 切片 → 查缓存 → 补算 → 存 chunk
async def ingest_document(document_id, filename, raw)   # parse_document → ingest_text
```

上传路径行为不变；社媒/快讯直接调 `ingest_text`。三条来源共用同一套切片、向量复用、
状态机（pending/processing/ready/failed）和错误处理。

### 整号订阅的两条路径

**回填**：`POST /api/kb/{kb_id}/sources` 建 `KbSource` 后触发后台回填，遍历该号在
`wechat_articles` 里已有的文章逐篇 resolve。因为查重幂等，该任务**重跑安全**——
进程重启丢了任务，下次 poll 或手动「同步」补上，不会产生重复。

**增量**：在 `poll_all_subscriptions` 中 `ingest_account` 返回后挂钩子——查哪些
`KbSource` 订阅了该 account，为本轮新增文章 resolve + 入库。

### 限速

这是整个设计里最脆的地方。补拉正文走共享凭证池，微信有风控。

- 进程内全局信号量把正文抓取串行化
- 每次请求间隔 `kb_backfill_delay_seconds`（默认 2s）
- 与用户点开文章的懒抓**共用同一个限流器**——否则后台回填会把前台阅读挤到超时
- 单篇失败标 `failed` 跳过，不中断整批
- 凭证池为空时整批暂停，而不是逐篇失败（否则一次回填能把几十篇全标脏）

### 配额

`user.role != "admin"` 时生效，管理员账号（开发调试用）不受限制：

```python
kb_max_documents_per_kb: int = 2000
kb_max_sources_per_user: int = 10
```

触顶时：手动加入返回 4xx 并带明确文案；订阅自动入库则把 `KbSource.status` 置为
`"limited"` 停止入库，并在知识库面板上显示可见提示，不静默丢弃。

## API

全部挂在现有 `/api/kb` 下：

```
GET    /api/kb/{kb_id}/documents            扩展返回字段，加 limit/offset 分页（默认 50）
GET    /api/kb/{kb_id}/documents/{doc_id}   文档详情（含全文）        ← 新增
DELETE /api/kb/{kb_id}/documents/{doc_id}   删除单条                  ← 新增
POST   /api/kb/{kb_id}/items                加入内容，收数组支持批量  ← 新增
POST   /api/kb/{kb_id}/sources              整号/信源订阅              ← 新增
GET    /api/kb/{kb_id}/sources              列出本库的订阅            ← 新增
DELETE /api/kb/{kb_id}/sources/{id}?purge=  断开订阅，purge=true 连带删文档 ← 新增
GET    /api/kb/{kb_id}/thread               取/建常驻会话             ← 新增
```

`POST /items` 的请求体是 `{items: [{source_type, source_ref_id}, ...]}`，返回
`{added: n, duplicate: n, failed: [{source_ref_id, error}]}`，前端据此提示
「3 条已加入，1 条已在库中」。单条失败不影响同批其余条目。

`GET /{kb_id}/thread` 照抄 `/api/news/thread` 的实现，但按 `(user_id, type="kb",
ref_id=kb_id)` 查找/创建。

路径统一为 `/{kb_id}/xxx/{id}` 三段式，不引入 `/api/kb/documents/{id}` 这种与
`/{kb_id}` 同层的路由——`router.py` 里关于 `/subscribed` 被当成 `kb_id` 吃掉的注释
说明这个坑已经踩过一次。

## 前端

### 布局

对话栏是**可折叠**的第四栏，默认收起，三栏浏览拿满宽度；展开后从右侧推出，详情和
对话同屏可见。

```
收起（默认）：
┌─────────┬────────────┬──────────────────────┬─┐
│ 知识库   │ 内容索引    │ 详情                  │◀│
│ ·研报库 │ ·文章A      │《XX月度策略》         │对│
│ ·宏观 ◂ │ ·文章B ◂    │ 2026-07-30 · 公众号   │话│
│ ·快讯   │ ·快讯C      │ 原文链接 ↗            │ │
│ +新建   │ ·report.pdf │ 正文……                │ │
└─────────┴────────────┴──────────────────────┴─┘

展开：
┌─────────┬──────────┬───────────────┬──────────────┐
│ 知识库   │ 内容索引  │ 详情           │ 对话      ▶ │
│ ·研报库 │ ·文章A    │《XX月度策略》  │ 你：本月政策 │
│ ·宏观 ◂ │ ·文章B ◂  │ 2026-07-30    │ 口径变化？   │
│ ·快讯   │ ·快讯C    │ 原文链接 ↗     │ AI：据《XX  │
│ +新建   │           │ 正文……         │ 月度策略》…  │
│         │           │                │ [提问… ↑]   │
└─────────┴──────────┴───────────────┴──────────────┘
```

### 组件拆分

`KbPanel.tsx` 现在 249 行做了全部事情，重写时按栏拆开：

```
KbPanel.tsx            容器：布局 + 选中态 + 折叠态
├─ KbList.tsx          库列表、新建、分享/订阅
├─ KbDocumentIndex.tsx 内容索引：按 published_at 倒序，来源图标，删除
├─ KbDocumentDetail.tsx 详情：标题/来源/时间/原文链接 + 入库文本正文
└─ KbAssistant.tsx     可折叠对话栏，RuntimeProvider + 锁定 mountedKbIds
```

详情区展示**入库时的文本快照**，不回源重抓——检索命中的就是这份文本，展示和检索
必须一致，否则用户会看到「AI 引用的内容和我看到的不一样」。原文链接单独给一个 `↗`。

对话是每个知识库一个 `type="kb"` 的常驻会话，折叠/切库/切面板回来历史都还在。

### 接入点

新增共用组件 `AddToKbDialog.tsx`（列出用户的知识库 + 「新建并加入」输入框），
四处复用：

- `SocialPanel` 文章卡片 hover 出图标 → 单篇加入（`/items`）
- `SocialPanel` 正文区顶部按钮 → 单篇加入
- `SocialPanel` 左侧订阅项 hover 出图标 → 整号加入（`/sources`）
- `NewsAssistant` 已有的「已选 N/5 条」操作行加「加入知识库」→ 批量加入（`/items`）

`lib/kb.ts` 相应扩展 API 封装。

## 失败模式

| 场景 | 处理 |
|---|---|
| 正文补拉失败（限流/凭证失效） | 该篇标 `failed` 记 error，回填继续下一篇；凭证池空则整批暂停 |
| embedding API 挂了 | 文档留在 `failed`，前端索引显示可重试；已入库的不受影响 |
| 同一篇被并发加入两次 | 唯一约束兜底，捕 `IntegrityError` 转 `duplicate` |
| 源文章被删 / 账号退订 | 文档保留，详情页原文链接可能 404，属预期 |
| 回填跑到一半进程重启 | 幂等，下次 poll 或手动「同步」自然补齐 |
| 触顶配额 | 手动加入返 4xx 带文案；订阅置 `status="limited"` 并在面板显示 |

## 测试

沿用 `backend/tests/test_kb_*.py` 的组织方式，`EMBEDDING_BACKEND=fake` 跑。

- `test_kb_dedup.py` — 同库重复加入返回 duplicate；不同库各存一份；并发插入被唯一约束挡住
- `test_kb_embedding_cache.py` — 相同文本第二次入库不调 provider（计数 fake 断言）；换 `embedding_model` 后不命中
- `test_kb_sources.py` — 订阅触发回填；poll 增量入库；断开订阅默认保留、`purge=true` 才删
- `test_kb_ingest.py`（扩展）— `ingest_text` 三条来源共用路径；失败写 `failed` 状态
- `test_kb_quota.py` — 普通账号触顶被拒；`role="admin"` 不受限
- 前端 — `KbPanel` 三栏选中联动；`AddToKbDialog` 建库并加入；重复提示文案

## 遗留风险

知识库现有的分享机制（`share_slug` + 订阅）意味着整号入库的公众号正文可以被分享给
任意拿到分享码的人。在「我攒资料」的语境下可接受，但若以后要做公开分享，需要按
`source_type` 限制可分享范围。本次沿用现状不加限制。
