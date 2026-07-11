# 社媒板块设计 — 微信公众号（一期）

日期：2026-07-10
状态：已与需求方逐段确认
上游：`docs/superpowers/specs/2026-07-06-d-sight-design.md`（社媒信源在一期"只留架构位"，本文档填实第一块——微信公众号）

## 1. 目标与范围

在 D-sight 投研助手中新增「社媒信息」板块。板块需支持多平台（微信公众号、微博大V、知识星球…），因各平台数据获取差异极大，一个一个做。**本期只做微信公众号**，其余平台只留 adapter 扩展位。

微信公众号一期能力：
- 用户扫码登录**自己的**公众号后台，凭证进入「凭证池」。
- 输入公众号名 → 搜索 → 订阅。
- 定时增量抓取订阅号的最近文章（元数据）。
- 文章正文**懒抓 + 纯文本**（用户打开或 agent 需要时才抓一次，缓存到库）。
- 文章落库，agent 可通过工具查询做投研分析。

**明确不做（本期）**：互动数据（阅读量/点赞/评论，需额外抓包 App credentials）、正文图片本地化与排版还原、微博/知识星球抓取。

## 2. 抓取原理（参考 wechat-article-exporter）

参考库 `/Users/weixi1/Documents/Study/wechat-article-exporter`（Nuxt/TS）。原理：登录一个微信公众号后台，利用后台"写文章→搜索其他公众号文章"功能抓取指定公众号全部文章。关键接口：

- **登录（三步，session cookies 须贯穿）**：
  1. `cgi-bin/scanloginqrcode?action=getqrcode` — 取二维码；响应 set-cookie 含 `uuid`，即本次登录 session 的锚。
  2. `cgi-bin/scanloginqrcode?action=ask`（带同一 session cookies）— **轮询**扫码/确认状态。
  3. `cgi-bin/bizlogin?action=login`（带同一 session cookies）— 换取登录态；从响应 `redirect_url` 抠 `token`，收集全部 set-cookie 即长期凭证。
- `cgi-bin/searchbiz?action=search_biz&query=<名>` — 按名搜公众号，返回候选（含 `fakeid`）。
- `cgi-bin/appmsgpublish?sub=list&fakeid=<id>&begin=&count=` — 按 fakeid 拉文章列表。**响应是双层 JSON 字符串**：顶层 `publish_page`（字符串）→ `JSON.parse` → `publish_list[]` → 每项 `publish_info`（字符串）→ `JSON.parse` → `appmsgex[]` 才是文章数组（一次群发含多篇）。另有 `total_count`；`publish_list` 空表示抓完。
- 正文 `mp.weixin.qq.com/s/xxx` 为公开 URL，无需登录即可 GET。

请求需带 `Referer/Origin: https://mp.weixin.qq.com`、桌面 UA。列表/搜索接口用 `token`（query）+ cookies（header）鉴权。

**微信返回码分类（关键，避免误杀凭证）**：
- `base_resp.ret == 0` → 成功。
- `base_resp.ret == 200003` → **会话失效** → 该凭证标 `expired`，换池。
- 其他非零（频控等）→ **临时错误**，退避重试或跳过本轮，**不**标 expired。

**限流风险**：微信按账号/IP 限流，参考库用公共代理池扛。本期用户量小（几十~几百）+ 懒抓纯文本，请求量低，**一期不引入代理池**，靠保守节流规避；量上来再加代理层（预留）。

## 3. 凭证模型（每用户登录 + 全局凭证池）

- **登录方**：每个终端用户扫码登录**自己的**公众号（有号才能用此板块）。
- **凭证池**：所有用户的有效凭证组成一个池。轮询/搜索时**从池里挑任一 active 凭证**去打微信接口，可抓任意用户订阅的号。投研数据本身是公共的，全局共享+凭证互助 → 省请求、抗限流、天然去重。
- **过期处理**：凭证约 4 天过期。到期标 `expired`，归属人前端提示重登；抓取任务自动改用池中另一 active 凭证。**池空 → 所有抓取暂停**，前端显示"需有人登录公众号"。
- **安全**：cookies 敏感，**Fernet 对称加密后入库**（密钥走环境变量/现有配置），读取时解密。token 同样加密存。

## 4. 数据模型（Postgres，4 表）

新增 `app/social/models.py`：

### `wechat_credentials`（凭证池）
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | FK users | 凭证归属人 |
| token | Text | 加密存 |
| cookies | Text | 加密存 |
| nickname | String | 公众号昵称 |
| avatar | String? | |
| expires_at | DateTime tz | ~登录+4天 |
| status | String(16) | active / expired |
| created_at / updated_at | DateTime tz | |

### `wechat_accounts`（全局公众号实体）
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| fakeid | String, **unique** | 微信侧号标识 |
| name | String | 公众号名 |
| avatar | String? | |
| signature | String? | 简介 |
| created_at | DateTime tz | |

### `wechat_articles`（全局文章）
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| account_id | FK wechat_accounts, index | |
| external_id | String | 微信侧文章唯一键 = `aid`（一次群发多篇，各篇 aid 不同，不能用 appmsgid） |
| title | String | ← `title` |
| digest | String? | 摘要 ← `digest` |
| cover_url | String? | 封面 ← `cover`（仅存 URL，不下载） |
| url | String | 正文链接 ← `link` |
| content | Text? | 纯文本正文，**懒抓填充**，初始 NULL |
| content_fetched_at | DateTime tz? | 正文抓取时间 |
| published_at | DateTime tz, index | |
| created_at | DateTime tz | |

约束：`unique(account_id, external_id)`（去重键，仿 news_items）。

### `wechat_subscriptions`（用户↔号）
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | FK users, index | |
| account_id | FK wechat_accounts | |
| enabled | Boolean, default true | |
| interval_seconds | Integer, default 1800 | 预留每订阅覆盖，默认 30min |
| created_at | DateTime tz | |

约束：`unique(user_id, account_id)`。

Alembic 迁移一支。

## 5. 抓取适配层（移植参考库 → Python/httpx）

### `app/social/wechat/login.py`
- `start_qrcode()` → 调 `getqrcode`，返二维码图片（base64/字节）+ 一个 login session id；session 存本次的 uuid cookies，落 **Redis**（已有依赖）带 TTL（如 5 分钟）。
- `poll_status(session_id)` → 带 session cookies 调 `scanloginqrcode?action=ask` 判断扫码/确认；确认后调 `bizlogin`，从 `redirect_url` 抠 `token`、收集 set-cookie，返 `nickname/avatar`，落 `wechat_credentials`（token+cookies 加密）。

### `app/social/wechat/client.py`
- `search_biz(keyword, cred)` → 公众号候选列表 `[{fakeid, name, avatar, signature}]`。
- `appmsg_publish(fakeid, begin, count, cred)` → 双层解析后返回 `appmsgex[]` 文章元数据。
- `fetch_article_text(url)` → GET 正文 HTML。
- 统一 `_mp_request()` 封装：注入 Referer/Origin/UA、token、解密后的 cookies；按 §2 返回码分类抛异常 —— `200003` 抛 `SessionExpiredError`（调用方标 expired），其他非零抛 `TransientMpError`（退避，不标 expired）。

### `app/social/wechat/parser.py`
- `html_to_text(html)` → 抠 `#js_content` 正文区，剥标签为纯文本（保留段落换行）。用现有 HTML 解析依赖（如 selectolax/bs4，取项目已有者）。

### `app/social/sources.py`（平台抽象位）
仿 `news/sources.py` 的 `NewsSource` ABC，定义 `SocialPlatform` ABC（`search / list_articles / fetch_text`），wechat 为首个实现。微博/知识星球后续加实现 + 在工厂注册。

## 6. 抓取与去重 `app/social/ingest.py`

仿 `news/ingest.py`：
- `pick_credential(db)` → 从池取一个 active 凭证（简单轮转/随机；过期的顺手标记）。池空抛 `NoCredentialError`。
- `ingest_account(db, account)` → 用池凭证 `appmsg_publish` 拉最近文章；按 `unique(account_id, external_id)` 去重，只插新的（`content=NULL`）。返回新增数。
- `fetch_article_content(db, article)` → 懒抓：`fetch_article_text` → `html_to_text` → 写 `content` + `content_fetched_at`。并发去重（同文章同时被请求时避免重复抓，简单行锁/乐观即可）。

## 7. 定时任务 `app/social/job.py`

- `poll_all_subscriptions()` — 取所有 enabled 订阅去重后的 account 集合；逐个 `ingest_account`，**串行 + 小 jitter** 保守节流；单账号失败隔离（仿 news job 的 try/except）。池空则整轮跳过并记日志。
- 注册进 `app/core/scheduler.py`：`IntervalTrigger(minutes=30)`，`id="social_poll"`。
- 单次抓取 `count=20`。

## 8. API `app/social/router.py`（prefix `/api/social`，全部 `get_current_user` 鉴权）

```
POST /wechat/login/qrcode         # 起扫码，返 {login_session, qrcode(img)}
GET  /wechat/login/status?s=      # 轮询；成功则存凭证，返 {status, nickname?}
GET  /wechat/credentials          # 我的凭证列表 + 状态
DELETE /wechat/credentials/{id}   # 登出/删除自己的凭证
GET  /wechat/search?keyword=      # 搜公众号（用池凭证）；池空返明确错误
POST /wechat/subscriptions        # body {fakeid, name, avatar?}；account 按 fakeid get-or-create，再建订阅（幂等）
GET  /wechat/subscriptions        # 我的订阅（含 account 信息）
DELETE /wechat/subscriptions/{id} # 退订
GET  /wechat/articles?account_id=&limit=20&before=  # 文章列表（元数据）
GET  /wechat/articles/{id}        # 正文；content 为空则懒抓+缓存后返回
POST /wechat/refresh?account_id=  # 手动抓一次该号最新
```

`schemas.py` 定义各 Out 模型（Pydantic）。

注册：`app/main.py` 增 `app.include_router(social_router)`。

## 9. Agent 工具 `app/agent/tools/social.py`

仿 `tools/news.py`：
```python
def make_wechat_query(session_factory):
    @tool
    async def wechat_query(account: str = "", keyword: str = "", days: int = 30, limit: int = 20) -> str:
        """查询已订阅公众号的文章。account 限定某号（名/模糊），keyword 关键词，days 时间窗。
        返回标题+正文摘要，用于投研分析。"""
        # 库内查 wechat_articles（join accounts）；content 为空的懒抓补全；
        # 全程 try/except 返回错误字符串，绝不向 agent 循环抛异常（同 news_query 取舍）。
```
注册进 `app/agent/tools/runner.py` 工具集。

## 10. 前端

### `frontend/src/lib/social.ts`（仿 `lib/news.ts`，走 `apiFetch`）
封装上述 API 的 TS 客户端 + 类型。

### `frontend/src/panels/SocialPanel.tsx`（替换占位）
- **平台切换**：顶部 tab（微信公众号 / 微博（禁用占位）/ 知识星球（禁用占位）），为多平台预留。
- **登录区**：无 active 凭证时显著提示"扫码登录公众号"；点开 Modal 显示二维码，轮询 `login/status`；显示已登录凭证昵称+状态（过期红标+重登）。
- **搜索/订阅**：输入公众号名 → 搜索结果卡片 → 「订阅」。
- **订阅列表**：左侧订阅号，右侧选中号的文章列表（标题/时间/摘要），点开抽屉读纯文本正文（懒抓 loading）。
- 手动「刷新」按钮 → `POST /wechat/refresh`。

## 11. 测试（TDD，仿 news）

- `wechat/client` 与 `parser`：喂 fixture JSON/HTML，断言解析出的元数据字段、纯文本正文。
- `ingest`：去重（重复 external_id 不重插）、懒抓填充 content。
- 凭证池：`pick_credential` 跳过 expired、池空抛错、过期自动标记。
- `wechat_query` 工具：命中/空窗/异常返错误字符串。
- `router`：鉴权、订阅 CRUD、正文懒抓路径。

## 12. 风险与合规

- 微信 ToS 灰区：仅服务用户自身抓取目的，不建账号池对外爬取（同参考库声明）。凭证只在本平台用户内互助，不对外。
- **知情同意**：凭证进共享池意味着可能被用于抓取其他用户订阅的号。登录界面须**明确告知**"你的登录将用于平台内共享抓取"，用户确认后再入池。承担被限流/风控的是登录者账号，须让其知情。
- 限流：保守节流；命中限流/登录失效码 → 凭证标 expired，换池。
- 内容版权归原作者，仅供用户投研参考。

## 13. 扩展位（后续平台）

- `SocialPlatform` ABC + 平台工厂 → 微博/知识星球加实现即可。
- 表设计：`wechat_*` 命名平台专属；若后续平台多，可抽象共享 `social_articles(platform, ...)`，本期不提前抽象（YAGNI）。
- 代理池：`_mp_request` 预留 proxy 参数位，量大时接入。
