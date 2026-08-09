# 微博账号信息获取：技术设计

## 设计目标

在不购买商业数据服务的前提下，为单个 D-sight 实例提供最多 20 个微博账号的实验性订阅能力。系统使用管理员配置的专用微博 Cookie，每 60 分钟低频获取原创微博；首次最多回溯 20 条，并把采集时快照同时提供给社媒页面和 Agent。

本设计不把网页内部接口包装成“公开 API”，也不承诺稳定性。数据入口被隔离在微博平台模块中，以便未来用授权数据源替换，而不改数据库、前端和 Agent 的消费契约。

## 关键选择

- **直接实现小型微博客户端，不部署 RSSHub/Puppeteer**：RSSHub 使用相同的 `m.weibo.cn` 内部接口和 Cookie，增加一个服务不能降低接口或合规风险。手动配置 Cookie 后，现有 `httpx` 足以完成首期需求。
- **保持平台专属模型和 API**：微信与微博的凭证、账号标识和内容结构差异明显。首期新增 `weibo_*` 模型与 `/api/social/weibo/*` API，不为两个平台提前构造通用 ORM 层；仅复用加密、调度和 UI 框架。
- **保存规范化快照，不保存上游原始响应**：数据库只保存产品需要的账号资料、纯文本正文、时间、原文链接和结构化媒体链接，减少对易变上游格式的耦合。
- **一个全局专用凭证，用户订阅独立**：Cookie 属于 D-sight 实例，由管理员维护；订阅仍按用户保存。20 个上限按全实例存在启用订阅的不同 UID 计算。
- **不拆成子任务**：数据库、API、前端与 Agent 共享同一内容契约，必须端到端验证；按实施阶段推进比并行拆分更能避免契约漂移。

## 数据流

```text
管理员 Cookie
    → 登录态验证与加密存储
微博主页链接
    → URL/UID 校验 → 账号预览与订阅
每小时调度或手动刷新
    → 微博客户端 → 响应校验 → 原创过滤 → 内容规范化
    → 唯一键去重 → PostgreSQL 快照
    ├→ 社媒页面
    └→ weibo_query Agent 工具
```

## 数据模型

模型继续放在 `app.social.models`，由一条 Alembic 迁移创建：

### `WeiboCredential`

- `id`: UUID
- `user_id`: 配置凭证的管理员 ID
- `cookies`: Fernet 加密后的 Cookie；永不通过 API 返回
- `weibo_uid`、`nickname`、`avatar`: `/api/config` 可获得时保存
- `status`: `active | expired | blocked`
- `last_verified_at`、`blocked_until`、`last_error`
- `created_at`、`updated_at`

保存新凭证时先调用 `https://m.weibo.cn/api/config`，只有 `data.login == true` 才加密落库；旧凭证改为 `expired`。Cookie 长度限制为 16 KiB，拒绝 CR/LF，避免请求头注入。

### `WeiboAccount`

- `id`: UUID
- `uid`: 微博数字 UID，全局唯一
- `name`、`avatar`、`description`、`profile_url`
- `last_synced_at`、`last_sync_status`、`last_sync_error`
- `created_at`、`updated_at`

账号预览会解析并持久化账号资料，但只有存在启用订阅的账号会进入定时同步。

### `WeiboPost`

- `id`: UUID
- `account_id`: FK → `WeiboAccount`
- `external_id`: 微博 status ID
- `bid`: 构造桌面原文链接使用的短 ID
- `content`: 规范化后的纯文本正文
- `url`: `https://weibo.com/{uid}/{bid}`
- `media`: JSONB 数组，元素契约为 `{type: "image" | "video", url: string, poster_url?: string}`
- `published_at`、`captured_at`、`created_at`
- 唯一约束：`(account_id, external_id)`

不设置内容更新流程；唯一键命中后直接跳过，数据库中的值即采集时快照。

### `WeiboSubscription`

- `id`: UUID
- `user_id`: FK → `User`
- `account_id`: FK → `WeiboAccount`
- `enabled`: bool
- `created_at`
- 唯一约束：`(user_id, account_id)`

新增订阅时在事务内锁定/统计具有启用订阅的不同账号；若新 UID 会使全实例超过 20 个则返回 409。取消最后一个订阅后停止轮询，但保留已有快照。

## 上游客户端与解析边界

新增 `app.social.weibo` 平台模块：

- `client.py`：唯一 HTTP 出口，统一移动端请求头、Cookie、超时和错误映射。
- `parser.py`：把未知 JSON 校验并转成 `WeiboProfile`、`RawWeiboPost` 等内部类型；HTML 正文转纯文本，媒体转统一数组。
- `errors.py`：`WeiboSessionExpiredError`、`WeiboRateLimitedError`、`WeiboTransientError`、`InvalidWeiboPayloadError`。
- `credentials.py`：选择/解密全局有效凭证、验证和过期处理。
- `cooldown.py`：使用 Redis 独立保存微博全局冷却状态，不与微信冷却键混用。
- `ingest.py`：分页、原创过滤、只补充新内容、唯一键去重和同步状态更新。
- `job.py`：遍历去重后的启用账号并控制整轮停止条件。

调用顺序：

1. `GET /api/config` 验证 Cookie 登录状态。
2. `GET /api/container/getIndex?type=uid&value={uid}` 获取账号资料和微博 `containerid`。
3. `GET /api/container/getIndex?...&containerid={containerid}&page={page}` 获取内容卡片。
4. 过滤没有 `mblog` 的卡片和包含 `retweeted_status` 的转发微博。
5. 先按 `external_id` 查询本地快照；仅对新内容调用 `GET /statuses/show?id={bid}` 补全长正文与媒体。
6. 初次最多获取 20 条原创内容；增量同步遇到已知的普通内容后停止，单轮最多翻 3 页、最多新增 20 条，避免无界回溯。

解析器只接受必要字段；缺失单条内容的非关键字段时跳过该条并记录日志，账号级结构失效则报 `InvalidWeiboPayloadError`，避免把登录页或错误页当内容写入数据库。

## API 契约

所有接口需要登录；凭证写操作复用现有 `app.admin.deps.require_admin`。

### 凭证

- `GET /api/social/weibo/credential`
  - 返回 `configured`、`status`、账号摘要、`last_verified_at`、`blocked_until`、`last_error`、`can_manage`
  - 不返回 Cookie 或其任何片段
- `PUT /api/social/weibo/credential`（管理员）
  - 输入 `{cookies}`，验证成功后替换全局凭证并清除旧冷却
- `DELETE /api/social/weibo/credential`（管理员）
  - 使凭证失效，不删除历史内容

### 账号与订阅

- `POST /api/social/weibo/accounts/preview`
  - 输入 `{profile_url}`；只接受 `weibo.com/u/{uid}`、`weibo.com/{uid}`、`m.weibo.cn/u/{uid}` 等可明确提取数字 UID 的主页链接
  - 返回 `account_id`、`uid`、`name`、`avatar`、`description`、`profile_url`
- `POST /api/social/weibo/subscriptions`
  - 输入 `{account_id}`；幂等创建用户订阅并执行首次同步
  - 返回订阅、`initial_sync_status` 和 `added`
- `GET /api/social/weibo/subscriptions`
- `DELETE /api/social/weibo/subscriptions/{subscription_id}`

### 内容

- `GET /api/social/weibo/posts?account_id=&before=&limit=`
  - 只允许读取当前用户已订阅的账号；`limit` 为 1–50，默认 20
- `POST /api/social/weibo/refresh?account_id=`
  - 只允许刷新当前用户已订阅的账号；设置单账号手动刷新冷却，避免连点

错误映射：Cookie 失效为 409；全局风控冷却为 429 并返回 `Retry-After`；临时上游错误为 503；非法主页链接为 422；无权限为 403；订阅上限为 409。

## 同步与风控

- APScheduler 新增独立 `weibo_poll`，默认 60 分钟，`max_instances=1`、`coalesce=True`。
- 一轮只同步存在启用订阅的不同账号，最多 20 个；账号之间留出短间隔，避免突发并发请求，不并行请求微博。
- `ok == -100` 或 `/api/config` 显示未登录：凭证标记 `expired`，终止整轮。
- HTTP 403/432：凭证标记 `blocked`，Redis 写入默认 24 小时全局冷却，终止整轮；页面展示恢复时间。管理员替换有效 Cookie 时清除冷却。
- 网络超时、5xx、单账号载荷异常：该账号记录 `error` 后继续下一个；不覆盖已有内容。
- 手动刷新遵循同一冷却，不提供绕过入口。

## 前端

- `SocialPanel` 增加“微博”Tab，微信页面行为不变。
- 微博页面独立为 `WeiboTab`，避免继续扩大现有 `WechatTab`。
- 左侧提供主页链接输入、账号预览、确认订阅、订阅列表和凭证状态；达到 20 个时显示明确上限文案。
- 管理员可粘贴 Cookie 并保存；输入框使用密码/多行隐藏显示，成功后立即清空。非管理员只看到“联系管理员配置”的状态。
- 右侧显示原创微博卡片、发布时间、图片缩略图和同步状态；详情显示纯文本、媒体链接及原文链接。
- 登录过期、风控冷却、临时失败分别显示可操作文案，不统一吞成“刷新失败”。

## Agent

新增 `make_weibo_query(session_factory, user_id)`：

- 参数：`account=""`、`keyword=""`、`days=30`、`limit=20`
- 查询 `WeiboPost`、`WeiboAccount` 和当前用户的启用 `WeiboSubscription`
- 输出发布时间、账号名、正文摘要和原文链接
- 注册为 `weibo_query` capability，并加入 Agent 构建工具列表
- 查询只读本地快照，绝不在 Agent 调用时访问微博

## 验证策略

- 上游测试全部 mock，不在自动测试中访问微博或使用真实 Cookie。
- 解析器覆盖：普通原创、长微博、图片/视频、转发过滤、置顶内容、缺字段、非 JSON。
- 客户端覆盖：有效/失效 Cookie、`ok=-100`、403、432、5xx、超时。
- 数据库与 API 覆盖：加密不回显、管理员权限、URL/UID 校验、20 账号上限、用户订阅隔离、首次 20 条、增量去重、快照不更新。
- Job 覆盖：每账号一次、失效/风控整轮停止、临时错误单号隔离、冷却期间零请求。
- 前端覆盖：微博 Tab、凭证角色状态、链接预览确认、列表/详情、错误与冷却文案。
- Agent 覆盖：账号/关键词/时间过滤及用户订阅隔离。

## 未来替换点

若后续购买授权数据，只替换 `app.social.weibo.client` 的上游实现；`WeiboProfile`、`RawWeiboPost`、数据库、API、前端和 Agent 契约保持不变。授权源若支持编辑/删除事件，再以新需求扩展快照语义。
