# 7x24 突发新闻 Timeline 面板设计

## 概述

将现有 `NewsPanel` 重构为 7:3 分栏布局：左侧 70% 为竖线时间轴新闻流，右侧 30% 为 AI 聊天界面（本期 stub）。

## 数据源

- **API**: `https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&page=1&page_size=20&type=0`
- **轮询间隔**: 后端 2min，前端 2min
- **过滤**: tag_id=0（全部分类）
- **响应关键字段**:
  - `id`: 唯一标识
  - `rich_text`: 新闻正文
  - `create_time`: 发布时间 (YYYY-MM-DD HH:MM:SS)
  - `tag[]`: 分类标签
  - `docurl`: 详情链接

## 架构决策

复用现有 `SinaLiveSource` + `NewsItem` 模型 + `poll_all_sources` job。不新增表、不新增 API 端点。仅调整轮询频率。

## 后端改动

| 项 | 现状 | 改为 |
|---|---|---|
| `NewsSource.interval_seconds` | 300 | 120 |
| 表结构 | 不变 | 不变 |
| API `/api/news` | 不变 | 不变 |
| `poll_all_sources` job | 不变 | 不变 |

## 前端设计

### 布局结构

```
NewsPanel (flex, h-full)
├── NewsTimeline (w-[70%], overflow-y-auto)
│   ├── 日期分隔头 (跨天时显示)
│   ├── TimelineNode
│   │   ├── 时间标记 (HH:MM)
│   │   ├── 竖线 + 圆点
│   │   └── 内容卡片 (title + content + url)
│   └── ... 更多节点
└── ChatStub (w-[30%], border-l)
    ├── 消息列表区 (空状态)
    └── 输入框 (disabled)
```

### NewsTimeline 组件

- 左侧贯穿竖线（`border-l-2`），每条新闻对应一个圆点节点
- 节点上方或左侧标注 `HH:MM`
- 跨天时插入日期分隔头（如 "07月08日"）
- 卡片内容：rich_text 正文，有 docurl 时显示链接
- 无限滚动：触底加载更多历史数据
- 新数据从顶部插入

### ChatStub 组件（本期占位，下期实现）

**设计目标（完整描述，暂不实现）：**

- 上下文感知：用户可选中左侧某条新闻，右侧 chat 自动以该新闻为上下文
- AI 能力：接入现有 RuntimeProvider，支持对新闻内容提问、分析、总结
- 交互流程：
  1. 用户点击左侧新闻节点 → 右侧显示"基于这条新闻提问"
  2. 用户输入问题 → AI 结合新闻内容回答
  3. 支持连续对话，保持新闻上下文
- 消息类型：用户消息、AI 回复、新闻引用卡片

**本期实现：**
- 静态占位 UI：消息列表空状态 + disabled 输入框
- 提示文案："AI 新闻助手即将上线"

### 轮询策略

- 前端 `setInterval` 每 120_000ms
- 请求 `/api/news?channel=news&after={最新一条的 published_at}`
- 新数据 prepend 到列表顶部
- 保留现有无限滚动加载历史逻辑

## 文件变更

| 文件 | 动作 | 说明 |
|---|---|---|
| `frontend/src/panels/NewsPanel.tsx` | 重构 | 改为 7:3 flex 容器 |
| `frontend/src/panels/NewsTimeline.tsx` | 新建 | 竖线时间轴组件 |
| `frontend/src/panels/ChatStub.tsx` | 新建 | 右侧聊天占位 |
| 后端 seed/config | 修改 | interval_seconds=120 |

## 不做的事

- 不新增数据库表
- 不新增后端 API
- 不实现右侧 chat 的 AI 交互（仅 stub）
- 不做 tag 筛选过滤
