# 微博账号信息获取：实施计划

## Phase 1：数据契约与迁移

1. 在 `backend/app/social/models.py` 增加 `WeiboCredential`、`WeiboAccount`、`WeiboPost`、`WeiboSubscription`，落实唯一约束、同步状态和 JSONB 媒体字段。
2. 新增 Alembic 迁移并验证 upgrade/downgrade；不得修改已有微信表。
3. 在 `backend/app/core/config.py` 增加 60 分钟轮询、20 账号/20 内容上限、请求间隔、手动刷新冷却和全局风控冷却配置。
4. 凭证写操作复用现有 `app.admin.deps.require_admin`；不新增角色判断，不改变普通登录流程。
5. 先写模型和迁移测试，确认唯一键与非空约束。

## Phase 2：微博客户端、解析器与凭证

1. 新建 `backend/app/social/weibo/` 包，先通过 fixture 驱动 `parser.py`：账号、原创/转发、长正文、媒体和时间解析。
2. 实现 `errors.py` 与 `client.py`，集中处理请求头、Cookie、JSON 校验、超时及 `-100/403/432/5xx` 映射。
3. 实现 `credentials.py`：管理员 Cookie 输入校验、`/api/config` 登录验证、Fernet 加密存储、选择/解密、替换和过期。
4. 实现独立 Redis `cooldown.py`；确认键名不与微信冲突，测试冷却剩余时间与清除。
5. 使用 `respx`/mock 响应完成客户端测试，自动测试禁止真实网络。

## Phase 3：采集、API 与调度

1. 实现 `ingest.py`：主页 URL 解析、账号预览、分页、原创过滤、先查重后补全、单轮限制、PostgreSQL 唯一键兜底和账号同步状态。
2. 新建 `backend/app/social/weibo/schemas.py` 和 `router.py`，实现凭证、预览、订阅、内容分页、取消订阅及手动刷新 API。
3. 在 API 层落实管理员权限、用户订阅所有权和全实例 20 个不同启用账号上限。
4. 实现 `job.py` 并在 `backend/app/core/scheduler.py` 注册独立 60 分钟任务；风控/失效中止整轮，临时错误只隔离单账号。
5. 在 `backend/app/social/router.py` 挂载微博 router，保持现有微信 URL 与行为不变。
6. 完成解析、采集、API、调度和错误映射测试；并运行现有全部 social 回归测试。

## Phase 4：Agent 查询

1. 在 `backend/app/agent/tools/social.py` 增加按当前用户订阅范围查询本地快照的 `weibo_query`。
2. 在 `backend/app/agent/build.py` 注入 `user_id` 并注册工具。
3. 在 `backend/app/agent/capability_registry.py` 注册 `weibo_query` 元数据。
4. 测试账号、关键词、时间、limit 和用户隔离；确认 Agent 查询不会调用上游微博。

## Phase 5：前端微博 Tab

1. 扩展 `frontend/src/lib/social.ts` 的微博类型和 API 方法，所有请求/响应字段与后端 schema 一一对应。
2. 新建 `frontend/src/panels/social/WeiboTab.tsx`，实现凭证状态、管理员 Cookie 配置、主页链接预览确认和订阅列表。
3. 实现微博快照列表/详情、图片与视频链接、原文跳转、首次同步和手动刷新状态。
4. 在 `SocialPanel.tsx` 添加微博 Tab；不改变现有 `WechatTab` 的交互。
5. 增加 API 与组件测试，覆盖非管理员、过期、冷却、上限和空状态。

## Phase 6：完整验证

1. 后端定向测试：`cd backend && uv run pytest tests/test_weibo_*.py tests/test_social_*.py`。
2. 后端静态检查：`cd backend && uv run ruff check app/social app/agent tests/test_weibo_*.py`。
3. 前端测试：`cd frontend && npx vitest run src/lib/social.test.ts src/panels/SocialPanel.test.tsx src/panels/social/WeiboTab.test.tsx`。
4. 前端构建与 lint：`cd frontend && npm run build && npm run lint`。
5. 迁移验证：在测试数据库执行 Alembic upgrade 到 head，并检查 downgrade/upgrade 往返。
6. 手工 smoke：用测试专用微博账号配置 Cookie、预览一个主页、订阅并同步；确认数据库和日志没有明文 Cookie。该步骤只在用户提供测试凭证后执行，不写入测试代码或仓库。

## 完成条件

- `prd.md` 的所有 Acceptance Criteria 有自动测试或明确的手工验证证据。
- 现有微信社媒功能和测试不回归。
- 不出现真实 Cookie、微博响应样本中的个人凭证或绕过冷却的代码。
- 完成实现后进入 Trellis check/review；未经用户要求不 commit、不 push。

## 验证记录（2026-08-06）

- `ruff`：通过。
- 前端定向测试：14/14 通过；`tsc -b` / Vite build 通过；Oxlint 通过，仅有 5 条任务外既有 warning。
- Alembic：单一 head `0a1b2c3d4e5f`；离线 upgrade/downgrade SQL 生成通过。
- OpenAPI：6 组 `/api/social/weibo/*` 路径已注册。
- 独立 Trellis check 已修复首次同步事务、Cookie 错误回显、置顶微博增量边界、同步状态展示和媒体类型契约问题，并补回归测试。
- Docker 启动后补验：微博与现有微信社媒测试共 90/90 通过；46 条 warning 均为既有测试 JWT 短密钥提示。
- 临时 PostgreSQL 迁移往返通过：`upgrade head → downgrade f0a1b2c3d4e5 → upgrade head`，四张微博表正确删除并恢复；测试容器已自动清理。
- 数据库补验仅修复两个测试隔离问题：全局账号上限与 Job 用例现在显式清理共享测试库中的微博订阅，生产逻辑未改动。
- 未使用真实 Cookie 或访问真实微博；未 commit、未 push。
