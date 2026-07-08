# 新闻 AI 助手实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将右侧 ChatStub 升级为 NewsAssistant，提供5个 AI 快捷分析功能（最近1小时总结、关键词搜索、多选总结/金融影响/时间线、股票分析两档）。

**Architecture:** 后端新增 threads.type 字段区分新闻线程与聊天线程，新增 `GET /api/news/thread`（get-or-create）和 keyword 搜索参数；前端 NewsAssistant 拥有独立 RuntimeProvider 实例，ActionZone 发送预构造的上下文消息，ChatStream 渲染流式结果，TimelineView 作为独立 view mode 渲染。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / Alembic；React 18 / TypeScript / Tailwind / shadcn/ui / @assistant-ui/react / TanStack Query

## Global Constraints

- 不新增数据库表（只加字段）
- 所有新增 API 端点必须走 `get_current_user` JWT 鉴权
- 前端不引入新第三方库
- context 字符串上限 5000 字符，超出截取并注明
- 多选上限 5 条，超出时 checkbox disabled

---

### Task 1: Backend — Thread type 字段 + migration

**Files:**
- Modify: `backend/app/threads/models.py`
- Modify: `backend/app/threads/router.py`
- Modify: `backend/app/threads/schemas.py`
- Create: `backend/alembic/versions/<hash>_threads_type.py`
- Test: `backend/tests/test_threads_type.py`

**Interfaces:**
- Produces: `Thread.type: str`（"chat" | "news"），`list_threads` 只返回 type="chat"

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_threads_type.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_list_threads_excludes_news_thread(client: AsyncClient, auth_headers: dict, db):
    from app.threads.models import Thread
    from app.auth.models import User
    from sqlalchemy import select

    # 查出当前测试用户
    user = (await db.execute(select(User))).scalars().first()
    news_thread = Thread(user_id=user.id, title="新闻助手", type="news")
    db.add(news_thread)
    await db.commit()

    r = await client.get("/api/threads/", headers=auth_headers)
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert str(news_thread.id) not in ids
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && python -m pytest tests/test_threads_type.py -v
```

Expected: AttributeError: type 字段不存在

- [ ] **Step 3: 修改 Thread 模型**

```python
# backend/app/threads/models.py — 在 deleted_at 之后加一行
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    type: Mapped[str] = mapped_column(String(20), default="chat", server_default="chat")
```

- [ ] **Step 4: 生成 Alembic migration**

```bash
cd backend && alembic revision --autogenerate -m "threads_type"
```

打开生成的文件，确认 upgrade() 包含：

```python
op.add_column('threads', sa.Column('type', sa.String(20), server_default='chat', nullable=False))
```

- [ ] **Step 5: 运行 migration**

```bash
cd backend && alembic upgrade head
```

Expected: 无报错

- [ ] **Step 6: 修改 list_threads 过滤**

```python
# backend/app/threads/router.py — list_threads 函数内
    rows = await db.scalars(
        select(Thread)
        .where(
            Thread.user_id == user.id,
            Thread.deleted_at.is_(None),
            Thread.type == "chat",
        )
        .order_by(Thread.updated_at.desc())
    )
```

- [ ] **Step 7: 运行测试确认通过**

```bash
cd backend && python -m pytest tests/test_threads_type.py -v
```

Expected: PASSED

- [ ] **Step 8: Commit**

```bash
git add backend/app/threads/models.py backend/app/threads/router.py \
        backend/alembic/versions/*threads_type* backend/tests/test_threads_type.py
git commit -m "feat(threads): add type field, filter list to chat threads only"
```

---

### Task 2: Backend — GET /api/news/thread + keyword 搜索

**Files:**
- Modify: `backend/app/news/router.py`
- Test: `backend/tests/test_news_thread.py`

**Interfaces:**
- Consumes: `Thread.type` from Task 1
- Produces:
  - `GET /api/news/thread` → `{"thread_id": str}`
  - `GET /api/news?keyword=str` → `list[NewsItemOut]`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_news_thread.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_news_thread_get_or_create_idempotent(client: AsyncClient, auth_headers: dict):
    r1 = await client.get("/api/news/thread", headers=auth_headers)
    r2 = await client.get("/api/news/thread", headers=auth_headers)
    assert r1.status_code == 200
    assert r1.json()["thread_id"] == r2.json()["thread_id"]

@pytest.mark.asyncio
async def test_news_keyword_search(client: AsyncClient, auth_headers: dict, db):
    from app.news.models import NewsItem
    import datetime as dt
    item = NewsItem(
        channel="news", title="苹果发布会", content="苹果公司发布新款iPhone",
        published_at=dt.datetime.now(dt.UTC),
    )
    db.add(item)
    await db.commit()

    r = await client.get("/api/news?keyword=苹果", headers=auth_headers)
    assert r.status_code == 200
    assert any("苹果" in i["content"] for i in r.json())

    r2 = await client.get("/api/news?keyword=腾讯", headers=auth_headers)
    assert r2.json() == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && python -m pytest tests/test_news_thread.py -v
```

Expected: 404 on /api/news/thread, keyword search returns all items

- [ ] **Step 3: 添加 keyword 参数**

```python
# backend/app/news/router.py — list_news 函数签名加参数
async def list_news(
    channel: str = "news",
    limit: int = Query(20, ge=1, le=50),
    before: dt.datetime | None = None,
    after: dt.datetime | None = None,
    keyword: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(NewsItem).where(NewsItem.channel == channel)
    if before is not None:
        q = q.where(NewsItem.published_at < before)
    if after is not None:
        q = q.where(NewsItem.published_at > after)
    if keyword:
        q = q.where(
            NewsItem.content.ilike(f"%{keyword}%") | NewsItem.title.ilike(f"%{keyword}%")
        )
    q = q.order_by(NewsItem.published_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [
        {"id": str(r.id), "channel": r.channel, "title": r.title, "content": r.content,
         "url": r.url, "published_at": r.published_at.isoformat()}
        for r in rows
    ]
```

- [ ] **Step 4: 添加 GET /api/news/thread 端点**

在 `router.py` 中 `list_news` 之前添加（路由顺序重要，/thread 需在 /{id} 之前）：

```python
@router.get("/thread")
async def get_news_thread(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.threads.models import Thread
    result = await db.execute(
        select(Thread).where(
            Thread.user_id == user.id,
            Thread.type == "news",
            Thread.deleted_at.is_(None),
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        thread = Thread(user_id=user.id, title="新闻助手", type="news")
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
    return {"thread_id": str(thread.id)}
```

`router.py` 顶部 imports 加：

```python
from sqlalchemy import select
```

（如已有则跳过）

- [ ] **Step 5: 运行测试确认通过**

```bash
cd backend && python -m pytest tests/test_news_thread.py -v
```

Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/app/news/router.py backend/tests/test_news_thread.py
git commit -m "feat(news): add /thread get-or-create endpoint and keyword search param"
```

---

### Task 3: Frontend — useNewsSelection hook

**Files:**
- Create: `frontend/src/hooks/useNewsSelection.ts`
- Test: `frontend/src/hooks/useNewsSelection.test.ts`

**Interfaces:**
- Produces:
  - `useNewsSelection()` → `{ selectedIds: Set<string>, selectedItems: NewsItem[], toggle(item): void, clear(): void, isFull: boolean }`
  - `hasStockMention(items: NewsItem[]): boolean`
  - `formatNewsContext(items: NewsItem[]): string`

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/src/hooks/useNewsSelection.test.ts
import { renderHook, act } from "@testing-library/react";
import { describe, test, expect } from "vitest";
import { useNewsSelection, hasStockMention, formatNewsContext } from "./useNewsSelection";
import type { NewsItem } from "@/lib/news";

const item = (id: string, content = "", title: string | null = null): NewsItem => ({
  id, channel: "news", title, content, url: null, published_at: "2026-07-08T10:00:00Z",
});

describe("useNewsSelection", () => {
  test("toggle adds item", () => {
    const { result } = renderHook(() => useNewsSelection());
    act(() => result.current.toggle(item("1", "test")));
    expect(result.current.selectedIds.has("1")).toBe(true);
    expect(result.current.selectedItems).toHaveLength(1);
  });

  test("toggle removes item on second call", () => {
    const { result } = renderHook(() => useNewsSelection());
    act(() => result.current.toggle(item("1")));
    act(() => result.current.toggle(item("1")));
    expect(result.current.selectedIds.has("1")).toBe(false);
    expect(result.current.selectedItems).toHaveLength(0);
  });

  test("caps at 5 items", () => {
    const { result } = renderHook(() => useNewsSelection());
    for (let i = 1; i <= 6; i++) act(() => result.current.toggle(item(String(i))));
    expect(result.current.selectedIds.size).toBe(5);
    expect(result.current.isFull).toBe(true);
  });

  test("clear resets all", () => {
    const { result } = renderHook(() => useNewsSelection());
    act(() => result.current.toggle(item("1")));
    act(() => result.current.clear());
    expect(result.current.selectedIds.size).toBe(0);
  });
});

describe("hasStockMention", () => {
  test("detects 6-digit code", () => {
    expect(hasStockMention([item("1", "000001大涨")])).toBe(true);
  });
  test("detects keyword 股票", () => {
    expect(hasStockMention([item("1", "股票市场")])).toBe(true);
  });
  test("detects ETF", () => {
    expect(hasStockMention([item("1", "", "ETF基金")])).toBe(true);
  });
  test("returns false when no match", () => {
    expect(hasStockMention([item("1", "今日天气晴")])).toBe(false);
  });
});

describe("formatNewsContext", () => {
  test("formats items with time and content", () => {
    const result = formatNewsContext([item("1", "内容A", "标题A")]);
    expect(result).toContain("标题A");
    expect(result).toContain("内容A");
  });

  test("truncates at 5000 chars", () => {
    const result = formatNewsContext([item("1", "a".repeat(6000))]);
    expect(result.length).toBeLessThan(5200);
    expect(result).toContain("内容已截取");
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd frontend && npx vitest run src/hooks/useNewsSelection.test.ts
```

Expected: Cannot find module './useNewsSelection'

- [ ] **Step 3: 实现 hook**

```typescript
// frontend/src/hooks/useNewsSelection.ts
import { useState, useCallback } from "react";
import type { NewsItem } from "@/lib/news";

const STOCK_PATTERN = /[0-9]{6}|股票|期货|ETF|基金|A股|港股/;
const MAX_SELECTION = 5;
const CONTEXT_MAX_CHARS = 5000;

export function hasStockMention(items: NewsItem[]): boolean {
  return items.some((i) => STOCK_PATTERN.test(i.content + (i.title ?? "")));
}

export function formatNewsContext(items: NewsItem[]): string {
  const lines = items.map((i) => {
    const d = new Date(i.published_at).toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    });
    return `[${d}] ${i.title ? i.title + ": " : ""}${i.content}`;
  });
  const text = lines.join("\n\n");
  if (text.length <= CONTEXT_MAX_CHARS) return text;
  return text.slice(0, CONTEXT_MAX_CHARS) + "\n\n（内容已截取）";
}

export function useNewsSelection() {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedItems, setSelectedItems] = useState<NewsItem[]>([]);

  const toggle = useCallback((item: NewsItem) => {
    setSelectedIds((prev) => {
      if (prev.has(item.id)) {
        setSelectedItems((items) => items.filter((i) => i.id !== item.id));
        const next = new Set(prev);
        next.delete(item.id);
        return next;
      }
      if (prev.size >= MAX_SELECTION) return prev;
      setSelectedItems((items) => [...items, item]);
      const next = new Set(prev);
      next.add(item.id);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setSelectedIds(new Set());
    setSelectedItems([]);
  }, []);

  return {
    selectedIds,
    selectedItems,
    toggle,
    clear,
    isFull: selectedIds.size >= MAX_SELECTION,
  };
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd frontend && npx vitest run src/hooks/useNewsSelection.test.ts
```

Expected: 所有测试 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useNewsSelection.ts frontend/src/hooks/useNewsSelection.test.ts
git commit -m "feat(news): useNewsSelection hook with stock detection and context formatter"
```

---

### Task 4: Frontend — lib/news.ts 加 keyword 参数

**Files:**
- Modify: `frontend/src/lib/news.ts`

**Interfaces:**
- Consumes: `GET /api/news?keyword=` from Task 2
- Produces: `fetchNews({ keyword?: string })` 支持关键词参数

- [ ] **Step 1: 修改 fetchNews**

```typescript
// frontend/src/lib/news.ts — fetchNews opts 加 keyword
export async function fetchNews(opts: {
  channel?: string;
  before?: string;
  after?: string;
  limit?: number;
  keyword?: string;
} = {}): Promise<NewsItem[]> {
  const p = new URLSearchParams();
  p.set("channel", opts.channel ?? "news");
  if (opts.before) p.set("before", opts.before);
  if (opts.after) p.set("after", opts.after);
  if (opts.limit) p.set("limit", String(opts.limit));
  if (opts.keyword) p.set("keyword", opts.keyword);
  const r = await apiFetch(`/api/news?${p.toString()}`);
  if (!r.ok) throw new Error("failed to load news");
  return r.json();
}

// 新增：获取新闻助手专属 threadId
export async function fetchNewsThreadId(): Promise<string> {
  const r = await apiFetch("/api/news/thread");
  if (!r.ok) throw new Error("failed to get news thread");
  const data = await r.json();
  return data.thread_id;
}
```

- [ ] **Step 2: 验证现有 news.test.ts 仍通过**

```bash
cd frontend && npx vitest run src/lib/news.test.ts
```

Expected: 所有测试 PASS（向后兼容）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/news.ts
git commit -m "feat(news): add keyword param and fetchNewsThreadId to news lib"
```

---

### Task 5: Frontend — NewsTimeline 加 checkbox

**Files:**
- Modify: `frontend/src/panels/NewsTimeline.tsx`

**Interfaces:**
- Consumes: `useNewsSelection` from Task 3 — `selectedIds: Set<string>`, `onToggle: (item: NewsItem) => void`, `isFull: boolean`
- Produces: NewsTimeline 接受 props，每条新闻左侧渲染 checkbox

- [ ] **Step 1: 修改组件签名**

```typescript
// frontend/src/panels/NewsTimeline.tsx — 顶部 import 加
import type { NewsItem } from "@/lib/news";

// 组件签名改为：
interface NewsTimelineProps {
  selectedIds: Set<string>;
  onToggle: (item: NewsItem) => void;
  isFull: boolean;
}

export default function NewsTimeline({ selectedIds, onToggle, isFull }: NewsTimelineProps) {
```

- [ ] **Step 2: 修改卡片渲染，加 checkbox**

找到 timeline items 的卡片部分（`<div key={item.id} className="relative pb-4 last:pb-1"`），在卡片最外层 div 内、`/* Dot */` 之前加：

```tsx
{/* Checkbox */}
<label
  className="absolute -left-[38px] top-[5px] flex items-center"
  onClick={(e) => e.stopPropagation()}
>
  <input
    type="checkbox"
    checked={selectedIds.has(item.id)}
    disabled={isFull && !selectedIds.has(item.id)}
    onChange={() => onToggle(item)}
    title={isFull && !selectedIds.has(item.id) ? "最多选5条" : undefined}
    className="h-3.5 w-3.5 cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-40"
  />
</label>
```

同时将时间轴左侧 padding 从 `pl-5` 改为 `pl-8`，为 checkbox 留空间：

```tsx
<div className="relative ml-1.5 border-l border-border/50 pl-8">
```

- [ ] **Step 3: 确认页面无 TypeScript 报错**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep NewsTimeline
```

Expected: 无输出（即无报错）。下一步 Task 7 会修 NewsPanel 传入 props。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/panels/NewsTimeline.tsx
git commit -m "feat(news): add checkbox to NewsTimeline items for multi-select"
```

---

### Task 6: Frontend — NewsAssistant 组件

**Files:**
- Create: `frontend/src/panels/NewsAssistant.tsx`

**Interfaces:**
- Consumes:
  - `RuntimeProvider` from `@/chat/RuntimeProvider` — props: `{ threadId: string, children: ReactNode }`
  - `Thread` from `@/chat/Thread`
  - `fetchNewsThreadId`, `fetchNews` from `@/lib/news`
  - `hasStockMention`, `formatNewsContext` from `@/hooks/useNewsSelection`
  - `selectedItems: NewsItem[]` via props

- [ ] **Step 1: 创建文件骨架，确认 import 路径正确**

```typescript
// frontend/src/panels/NewsAssistant.tsx
import { useEffect, useRef, useState } from "react";
import { Zap, Search, BarChart2, ChevronLeft } from "lucide-react";
import { RuntimeProvider } from "@/chat/RuntimeProvider";
import { Thread } from "@/chat/Thread";
import { fetchNews, fetchNewsThreadId, type NewsItem } from "@/lib/news";
import { hasStockMention, formatNewsContext } from "@/hooks/useNewsSelection";
import { useAssistantRuntime } from "@assistant-ui/react";

interface NewsAssistantProps {
  selectedItems: NewsItem[];
}

export default function NewsAssistant({ selectedItems }: NewsAssistantProps) {
  return <div>placeholder</div>;
}
```

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep NewsAssistant
```

Expected: 无报错（如有缺失 import 先修复）

- [ ] **Step 2: 实现 threadId 加载 + RuntimeProvider 包裹**

```typescript
export default function NewsAssistant({ selectedItems }: NewsAssistantProps) {
  const [threadId, setThreadId] = useState<string | null>(null);

  useEffect(() => {
    fetchNewsThreadId().then(setThreadId).catch(console.error);
  }, []);

  if (!threadId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        正在加载…
      </div>
    );
  }

  return (
    <RuntimeProvider key={threadId} threadId={threadId}>
      <NewsAssistantInner selectedItems={selectedItems} />
    </RuntimeProvider>
  );
}
```

- [ ] **Step 3: 实现 NewsAssistantInner（ActionZone + ChatStream + TimelineView）**

```typescript
type ViewMode = "chat" | "timeline";

function NewsAssistantInner({ selectedItems }: NewsAssistantProps) {
  const runtime = useAssistantRuntime();
  const [viewMode, setViewMode] = useState<ViewMode>("chat");
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [showDeepAnalysis, setShowDeepAnalysis] = useState(false);
  const hasStock = hasStockMention(selectedItems);

  // 发送带 context 的消息
  const sendWithContext = (context: string, prompt: string) => {
    const text = context
      ? `以下是相关新闻：\n\n${context}\n\n---\n${prompt}`
      : prompt;
    runtime.thread.composer.setInput(text);
    runtime.thread.composer.send();
    setShowDeepAnalysis(false);
  };

  // 功能1: 最近1小时总结
  const handleRecentHour = async () => {
    setLoading(true);
    try {
      const after = new Date(Date.now() - 3600_000).toISOString();
      const items = await fetchNews({ after, limit: 50 });
      if (items.length === 0) {
        runtime.thread.composer.setInput("（最近1小时暂无快讯）");
        runtime.thread.composer.send();
        return;
      }
      sendWithContext(formatNewsContext(items), "请总结以上最近1小时新闻要点。");
    } finally {
      setLoading(false);
    }
  };

  // 功能2: 关键词搜索
  const handleKeywordSearch = async () => {
    if (!keyword.trim()) return;
    setLoading(true);
    try {
      const items = await fetchNews({ keyword: keyword.trim(), limit: 20 });
      if (items.length === 0) {
        runtime.thread.composer.setInput(`（未找到含"${keyword}"的新闻，可尝试其他关键词）`);
        runtime.thread.composer.send();
        return;
      }
      sendWithContext(formatNewsContext(items), `请总结以下关于"${keyword}"的新闻。`);
    } finally {
      setLoading(false);
    }
  };

  // 功能3: 多选总结
  const handleSummarize = () => {
    sendWithContext(formatNewsContext(selectedItems), "请总结以下新闻并给出你的看法。");
  };

  // 功能3: 金融影响
  const handleFinancialImpact = () => {
    sendWithContext(formatNewsContext(selectedItems), "请分析以下新闻对金融、股票市场的潜在影响。");
  };

  // 功能5: 股票分析（轻量）
  const handleStockAnalysis = () => {
    sendWithContext(
      formatNewsContext(selectedItems),
      "请分析以下新闻中涉及标的（股票、期货、ETF 等）的投资影响，包括短期价格催化剂和潜在风险。",
    );
    setShowDeepAnalysis(true);
  };

  // 功能5: 深度分析
  const handleDeepAnalysis = () => {
    sendWithContext(
      formatNewsContext(selectedItems),
      "请使用 ai-berkshire skill 对新闻中涉及的股票标的进行价值分析，包括基本面评估和投资建议。",
    );
    setShowDeepAnalysis(false);
  };

  return (
    <div className="flex h-full flex-col">
      {/* ActionZone */}
      <div className="shrink-0 border-b border-border/60 px-3 py-2 space-y-2">
        {/* Row 1: 快捷按钮 + 搜索 */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRecentHour}
            disabled={loading}
            className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50 whitespace-nowrap"
          >
            <Zap className="size-3" />
            最近1小时
          </button>
          <div className="flex flex-1 items-center gap-1">
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleKeywordSearch()}
              placeholder="关键词搜索…"
              className="flex-1 min-w-0 rounded-md border border-border bg-transparent px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-primary/50"
            />
            <button
              type="button"
              onClick={handleKeywordSearch}
              disabled={loading || !keyword.trim()}
              className="rounded-md border border-border p-1 hover:bg-accent disabled:opacity-50"
            >
              <Search className="size-3" />
            </button>
          </div>
        </div>

        {/* Row 2: 选中操作（仅在有选中时显示） */}
        {selectedItems.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] text-muted-foreground whitespace-nowrap">
              已选 {selectedItems.length}/5 条
            </span>
            <button type="button" onClick={handleSummarize}
              className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-accent">
              总结
            </button>
            <button type="button" onClick={handleFinancialImpact}
              className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-accent">
              金融影响
            </button>
            <button type="button" onClick={() => setViewMode("timeline")}
              className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-accent">
              时间线
            </button>
            {hasStock && (
              <button type="button" onClick={handleStockAnalysis}
                className="flex items-center gap-0.5 rounded-md border border-amber-500/50 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-600 hover:bg-amber-500/20">
                <BarChart2 className="size-3" />
                股票分析
              </button>
            )}
            {showDeepAnalysis && (
              <button type="button" onClick={handleDeepAnalysis}
                className="rounded-md border border-primary/50 bg-primary/10 px-2 py-0.5 text-xs text-primary hover:bg-primary/20">
                深度分析
              </button>
            )}
          </div>
        )}
      </div>

      {/* Content: ChatStream 或 TimelineView */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {viewMode === "timeline" ? (
          <TimelineView items={selectedItems} onBack={() => setViewMode("chat")} />
        ) : (
          <Thread />
        )}
      </div>
    </div>
  );
}

function TimelineView({ items, onBack }: { items: NewsItem[]; onBack: () => void }) {
  const sorted = [...items].sort(
    (a, b) => new Date(a.published_at).getTime() - new Date(b.published_at).getTime(),
  );
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
        <span className="text-xs font-medium">新闻时间线（{sorted.length} 条）</span>
        <button type="button" onClick={onBack}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ChevronLeft className="size-3" />
          返回
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-3">
        <div className="relative ml-1 border-l border-border/50 pl-4 space-y-3">
          {sorted.map((item) => (
            <div key={item.id} className="relative">
              <div className="absolute -left-[17px] top-[6px] h-2 w-2 rounded-full bg-primary/60" />
              <div className="text-[11px] tabular-nums text-muted-foreground mb-0.5">
                {new Date(item.published_at).toLocaleString("zh-CN", {
                  month: "2-digit", day: "2-digit",
                  hour: "2-digit", minute: "2-digit", hour12: false,
                })}
              </div>
              {item.title && (
                <div className="text-[13px] font-medium mb-0.5">{item.title}</div>
              )}
              <p className="text-[13px] leading-[1.6] text-muted-foreground">{item.content}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 确认 TypeScript 无报错**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "newsassistant\|news_assistant"
```

Expected: 无输出

- [ ] **Step 5: Commit**

```bash
git add frontend/src/panels/NewsAssistant.tsx
git commit -m "feat(news): NewsAssistant component with ActionZone, ChatStream, and TimelineView"
```

---

### Task 7: Frontend — NewsPanel 串联所有组件

**Files:**
- Modify: `frontend/src/panels/NewsPanel.tsx`

**Interfaces:**
- Consumes: `useNewsSelection` (Task 3), `NewsTimeline` props (Task 5), `NewsAssistant` (Task 6)

- [ ] **Step 1: 重写 NewsPanel**

```typescript
// frontend/src/panels/NewsPanel.tsx
import { useNewsSelection } from "@/hooks/useNewsSelection";
import NewsTimeline from "./NewsTimeline";
import NewsAssistant from "./NewsAssistant";

export default function NewsPanel() {
  const { selectedIds, selectedItems, toggle, isFull } = useNewsSelection();

  return (
    <div className="flex h-full">
      <div className="w-[70%] min-w-0">
        <NewsTimeline
          selectedIds={selectedIds}
          onToggle={toggle}
          isFull={isFull}
        />
      </div>
      <div className="w-[30%] border-l border-border">
        <NewsAssistant selectedItems={selectedItems} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 全量 TypeScript 检查**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors

- [ ] **Step 3: 运行前端并手动验证**

```bash
bash dev.sh
```

打开浏览器，进入新闻面板，验证：
1. 每条新闻左侧有 checkbox
2. 勾选1条 → 右侧出现"总结/金融影响/时间线"按钮
3. 勾选含"000001"或"股票"字样的新闻 → 出现"股票分析"按钮
4. 勾选6条 → 第6条 checkbox disabled
5. 点"最近1小时" → 右侧开始流式输出
6. 输入关键词回车 → 右侧流式输出搜索总结
7. 点"时间线" → 进入时间线视图，点"返回"回到聊天
8. 点"股票分析"完成后 → 出现"深度分析"按钮

- [ ] **Step 4: Commit**

```bash
git add frontend/src/panels/NewsPanel.tsx
git commit -m "feat(news): wire NewsPanel with selection state, NewsTimeline checkboxes, NewsAssistant"
```
