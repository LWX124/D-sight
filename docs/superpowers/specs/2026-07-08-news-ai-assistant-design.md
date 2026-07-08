# 新闻 AI 助手设计文档

日期：2026-07-08
状态：已与需求方逐段确认

## 概述

在现有 7x24 新闻时间轴（`NewsTimeline`）基础上，将右侧 `ChatStub` 升级为 `NewsAssistant`——一个"操作区 + 流式聊天区"的两层面板，为用户提供5个 AI 驱动的快捷新闻分析功能。

## 布局结构

```
NewsPanel (7:3 flex, h-full)
├── NewsTimeline (70%) — 改：加 checkbox
└── NewsAssistant (30%) — 替换 ChatStub
    ├── ActionZone (固定高度 ~110px)
    │   ├── Row1: [⚡ 最近1小时]  [🔍 关键词搜索框]
    │   └── Row2: 选中 ≥1 条时出现
    │       ├── 已选 N/5 条 badge
    │       ├── [总结]  [金融影响]  [时间线]
    │       └── [📈 股票分析]（仅当选中新闻含股票/期货标识时）
    └── ChatStream (flex-1, 可滚动)
        └── 独立 RuntimeProvider 实例（与主聊天隔离）
```

## 5个功能的数据流

### 功能1 — 最近1小时总结

```
点击 [⚡ 最近1小时]
→ 前端调 GET /api/news?after={now-1h}&limit=50
→ 格式化条目为 context 字符串
→ 发消息给 RuntimeProvider："请总结以上最近1小时新闻要点"
→ ChatStream 流式输出
```

### 功能2 — 关键词搜索总结

```
输入关键词 + 回车
→ 前端调 GET /api/news?keyword=xxx&limit=20
→ 有结果 → 注入 context → 发"请总结以下关于{词}的新闻"
→ 无结果 → ChatStream 显示"暂无相关新闻"
```

### 功能3 — 多选总结 / 金融影响

```
选中 1-5 条 → 点 [总结] 或 [金融影响]
→ 取前端内存中已有的新闻内容（无需再请求后端）
→ 不同 system prompt:
    总结:    "请总结以下新闻并给出你的看法"
    金融影响: "请分析以下新闻对金融、股票市场的潜在影响"
→ 流式输出
```

### 功能4 — 新闻时间线整理

```
选中 1-5 条 → 点 [时间线]
→ 纯前端：按 published_at 排序选中条目
→ NewsAssistant 切换到 TimelineView 模式（替换 ChatStream 区域显示）
→ 渲染排序后的时间线列表，右上角有"返回"按钮退出此模式
→ 不调 LLM，不经过 RuntimeProvider
```

> 注：时间线视图作为独立 view mode 渲染，不注入到 RuntimeProvider 消息流，避免类型冲突。

### 功能5 — 股票分析（两档）

```
触发条件：选中新闻 content 含 A股/港股代码或"股票/期货/ETF/基金"等关键词
→ ActionZone 出现 [📈 股票分析] 按钮

轻量路（默认）:
  → 注入 context + "分析涉及标的的投资影响" → 流式输出

深度分析（轻量完成后出现）:
  → 发特殊 prompt "use ai-berkshire skill: 对[标的]做价值分析"
  → agent 自行调用已安装 ai-berkshire skill
```

## 文件变更清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `frontend/src/panels/NewsAssistant.tsx` | 新建 | 替换 ChatStub，包含 ActionZone + ChatStream/TimelineView |
| `frontend/src/panels/NewsTimeline.tsx` | 修改 | 加 checkbox，选中状态通过 props 回调 |
| `frontend/src/panels/NewsPanel.tsx` | 修改 | 持有选中状态，传给 NewsTimeline 和 NewsAssistant |
| `frontend/src/hooks/useNewsSelection.ts` | 新建 | 选中逻辑：5条上限、股票检测、格式化 context |
| `backend/app/news/router.py` | 修改 | 加 `keyword` 参数 + 新增 `GET /api/news/thread` |
| `backend/app/threads/models.py` | 修改 | 加 `type` 字段，默认 `"chat"` |
| `backend/app/threads/router.py` | 修改 | `list_threads` 过滤 `type="chat"` |
| `backend/alembic/versions/` | 新增 | threads.type 字段 migration |

## 后端改动（最小化）

`router.py` 加5行：

```python
keyword: str | None = None,
# ...
if keyword:
    q = q.where(
        NewsItem.content.ilike(f"%{keyword}%") | NewsItem.title.ilike(f"%{keyword}%")
    )
```

## 股票检测逻辑

```typescript
// 正则匹配 A股6位代码、港股代码，或关键词
const STOCK_PATTERN = /[0-9]{6}|股票|期货|ETF|基金|A股|港股/
function hasStockMention(items: NewsItem[]): boolean {
  return items.some(i => STOCK_PATTERN.test(i.content + (i.title ?? "")))
}
```

## RuntimeProvider 隔离与 ThreadId

`NewsAssistant` 使用独立的固定 per-user "新闻助手" thread，与主聊天线程隔离。

**实现方案：**
- `Thread` 模型新增 `type: str = "chat"` 字段（Alembic migration）
- `list_threads` 只返回 `type="chat"` 的记录，新闻 thread 不出现在聊天侧边栏
- 新增后端端点 `GET /api/news/thread`（get-or-create）：查询当前用户的 `type="news"` thread，不存在则创建，返回 threadId
- NewsAssistant 挂载时调用此端点取 threadId，再初始化 `RuntimeProvider`

**文件变更补充：**

| 文件 | 动作 |
|---|---|
| `backend/app/threads/models.py` | 加 `type` 字段，默认 `"chat"` |
| `backend/app/threads/router.py` | `list_threads` 加 `type="chat"` 过滤 |
| `backend/app/news/router.py` | 新增 `GET /api/news/thread` get-or-create |
| `alembic/versions/` | 新增 migration：threads.type 字段 |

## 错误处理

| 场景 | 处理 |
|---|---|
| 最近1小时无新闻 | ChatStream 显示提示卡片"最近1小时暂无快讯" |
| 关键词无结果 | 提示"未找到含'{词}'的新闻，可尝试其他关键词" |
| LLM 请求失败/超时 | ChatStream 显示错误提示，ActionZone 按钮恢复可点击 |
| 选5条后再点其他 checkbox | checkbox disabled，hover 提示"最多选5条" |
| 选中新闻 context 过长 | 截取前5000字符，末尾注明"（内容已截取）" |
| 深度分析 skill 不可用 | 降级为轻量分析，toast 提示"深度分析暂不可用" |

## 不做的事

- 不新增数据库表
- 不新增除 `keyword` 参数之外的后端路由
- 不做新闻标注/打标签持久化
- 不做跨 session 的选中状态保留
