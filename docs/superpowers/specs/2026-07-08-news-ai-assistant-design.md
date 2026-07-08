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
→ ChatStream 渲染自定义"时间线消息"（不调 LLM）
```

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
| `frontend/src/panels/NewsAssistant.tsx` | 新建 | 替换 ChatStub，包含 ActionZone + ChatStream |
| `frontend/src/panels/NewsTimeline.tsx` | 修改 | 加 checkbox，选中状态通过 props 回调 |
| `frontend/src/panels/NewsPanel.tsx` | 修改 | 持有选中状态，传给 NewsTimeline 和 NewsAssistant |
| `frontend/src/hooks/useNewsSelection.ts` | 新建 | 选中逻辑：5条上限、股票检测、格式化 context |
| `backend/app/news/router.py` | 修改 | `GET /api/news` 加 `keyword: str | None` 参数 |

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
const STOCK_PATTERN = /[0-9]{6}|[港股][票]|股票|期货|ETF|基金|A股|港股/
function hasStockMention(items: NewsItem[]): boolean {
  return items.some(i => STOCK_PATTERN.test(i.content + (i.title ?? "")))
}
```

## RuntimeProvider 隔离

`NewsAssistant` 创建独立的 `AssistantRuntime` 实例，与主聊天页面的线程完全隔离，新闻上下文不污染主对话历史。

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
