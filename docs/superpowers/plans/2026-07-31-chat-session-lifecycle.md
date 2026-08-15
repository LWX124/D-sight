# 会话生命周期修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复会话模块三个问题：点击"+"不跳转、空白会话不应入库、历史按聊天时间倒序排列。

**Architecture:** 前端引入 URL 路由 `/chat/new` 和 `/chat/:threadId`，草稿态不调用后端；首次发送时创建 thread 并切换 URL；后端新增 `last_message_at` 字段并在聊天时更新，历史按该字段倒序排列。

**Tech Stack:** React Router, React Query, FastAPI, SQLAlchemy, Alembic, PostgreSQL, pytest

## Global Constraints

- Python ≥ 3.12
- 所有数据库时间戳使用 `DateTime(timezone=True)` 和 UTC
- 前端 API 调用通过 `apiFetch` 包装，自动处理 401 刷新
- 测试使用 pytest + httpx AsyncClient
- 迁移文件命名格式：`<revision>_<descriptive_name>.py`
- Git commit 消息遵循 Conventional Commits，中文正文，末尾署名 `Co-Authored-By: Claude <noreply@anthropic.com>`

---

### Task 1: 数据库迁移 - 添加 last_message_at 字段

**Files:**
- Create: `backend/alembic/versions/<new_revision>_thread_last_message_at.py`
- Modify: `backend/app/threads/models.py:11-27`
- Modify: `backend/app/threads/schemas.py:14-18`

**Interfaces:**
- Produces: `Thread.last_message_at: Mapped[datetime]` 字段，索引 `ix_threads_last_message_at`

- [ ] **Step 1: 生成迁移文件**

```bash
cd backend
alembic revision -m "thread_last_message_at"
```

预期输出类似：`Generating /Users/.../backend/alembic/versions/abc123def456_thread_last_message_at.py`

- [ ] **Step 2: 编写迁移 upgrade 逻辑**

打开生成的迁移文件，在 `upgrade()` 函数中添加：

```python
def upgrade() -> None:
    # 添加字段，允许 NULL
    op.add_column('threads', sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True))
    
    # 数据迁移：将现有 threads 的 last_message_at 初始化为 updated_at
    op.execute("UPDATE threads SET last_message_at = updated_at WHERE last_message_at IS NULL")
    
    # 设置为非空约束
    op.alter_column('threads', 'last_message_at', nullable=False)
    
    # 新增索引
    op.create_index(op.f('ix_threads_last_message_at'), 'threads', ['last_message_at'], unique=False)
```

- [ ] **Step 3: 编写迁移 downgrade 逻辑**

在同一文件的 `downgrade()` 函数中添加：

```python
def downgrade() -> None:
    op.drop_index(op.f('ix_threads_last_message_at'), table_name='threads')
    op.drop_column('threads', 'last_message_at')
```

- [ ] **Step 4: 更新 Thread 模型**

修改 `backend/app/threads/models.py`，在 `updated_at` 字段后添加：

```python
last_message_at: Mapped[dt.datetime] = mapped_column(
    DateTime(timezone=True), 
    nullable=False, 
    index=True,
    server_default=func.now()
)
```

- [ ] **Step 5: 更新 ThreadOut schema**

修改 `backend/app/threads/schemas.py`，在 `ThreadOut` 类中添加字段：

```python
class ThreadOut(BaseModel):
    id: str
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime
    last_message_at: dt.datetime
```

- [ ] **Step 6: 运行迁移**

```bash
cd backend
alembic upgrade head
```

预期输出包含：`Running upgrade ... -> <new_revision>, thread_last_message_at`

- [ ] **Step 7: 验证迁移**

```bash
cd backend
python -c "
from sqlalchemy import create_engine, inspect
from app.core.config import get_settings
engine = create_engine(get_settings().database_url.replace('postgresql+asyncpg://', 'postgresql://'))
inspector = inspect(engine)
cols = {c['name']: c for c in inspector.get_columns('threads')}
assert 'last_message_at' in cols, 'last_message_at 字段不存在'
assert not cols['last_message_at']['nullable'], 'last_message_at 应为非空'
indexes = [idx['name'] for idx in inspector.get_indexes('threads')]
assert 'ix_threads_last_message_at' in indexes, '索引不存在'
print('✓ 迁移验证通过')
"
```

预期输出：`✓ 迁移验证通过`

- [ ] **Step 8: Commit**

```bash
git add backend/alembic/versions/*_thread_last_message_at.py backend/app/threads/models.py backend/app/threads/schemas.py
git commit -m "feat(threads): 添加 last_message_at 字段用于聊天时间排序

- 新增数据库字段和索引
- 现有数据初始化为 updated_at
- ThreadOut schema 包含新字段

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 后端列表排序和聊天更新 last_message_at

**Files:**
- Modify: `backend/app/threads/router.py:46-59`
- Modify: `backend/app/chat/router.py:70-80`

**Interfaces:**
- Consumes: `Thread.last_message_at` 字段（来自 Task 1）
- Produces: 列表按 `last_message_at DESC, created_at DESC, id DESC` 排序；聊天时更新 `last_message_at`

- [ ] **Step 1: 编写列表排序测试**

创建 `backend/tests/test_threads_last_message_at.py`:

```python
import asyncio
from tests.test_auth_api import _register


async def _auth_headers(client, db_session, email: str) -> dict:
    token = await _register(client, db_session, email)
    return {"Authorization": f"Bearer {token}"}


async def test_threads_sorted_by_last_message_at(client, db_session):
    """历史列表按 last_message_at 倒序，重命名不影响排序"""
    headers = await _auth_headers(client, db_session, "sort@test.dev")
    
    # 创建三个 thread
    tid_a = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]
    await asyncio.sleep(0.01)
    tid_b = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]
    await asyncio.sleep(0.01)
    tid_c = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]
    
    # 初始顺序：c, b, a（按创建时间倒序）
    threads = (await client.get("/api/threads/", headers=headers)).json()
    assert [t["id"] for t in threads] == [tid_c, tid_b, tid_a]
    
    # 重命名 a，不应改变排序
    await client.patch(f"/api/threads/{tid_a}", json={"title": "重命名"}, headers=headers)
    threads = (await client.get("/api/threads/", headers=headers)).json()
    assert [t["id"] for t in threads] == [tid_c, tid_b, tid_a], "重命名不应置顶"
    
    # 模拟给 b 发送消息（通过直接更新 last_message_at）
    from app.core.db import get_sessionmaker
    from app.threads.models import Thread
    from datetime import UTC, datetime
    from sqlalchemy import select, update
    import uuid
    
    async with get_sessionmaker().begin() as db:
        await db.execute(
            update(Thread)
            .where(Thread.id == uuid.UUID(tid_b))
            .values(last_message_at=datetime.now(UTC))
        )
    
    await asyncio.sleep(0.01)
    
    # 现在顺序应为：b, c, a
    threads = (await client.get("/api/threads/", headers=headers)).json()
    assert [t["id"] for t in threads] == [tid_b, tid_c, tid_a], "发送消息应置顶"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend
pytest tests/test_threads_last_message_at.py::test_threads_sorted_by_last_message_at -v
```

预期输出：`FAILED` （因为排序逻辑尚未修改）

- [ ] **Step 3: 修改列表排序**

修改 `backend/app/threads/router.py`，将 `list_threads` 函数的排序逻辑改为：

```python
@router.get("/")
async def list_threads(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ThreadOut]:
    stmt = (
        select(Thread)
        .where(Thread.user_id == user.id, Thread.deleted_at.is_(None))
        .order_by(
            Thread.last_message_at.desc(),
            Thread.created_at.desc(),
            Thread.id.desc()
        )
    )
    result = await db.execute(stmt)
    return [_out(t) for t in result.scalars()]
```

- [ ] **Step 4: 编写聊天更新 last_message_at 的测试**

在 `backend/tests/test_chat_api.py` 中添加测试：

```python
async def test_chat_updates_last_message_at(client, db_session):
    """发送聊天消息应更新 thread 的 last_message_at"""
    from tests.test_auth_api import _register
    from app.core.db import get_sessionmaker
    from app.threads.models import Thread
    from sqlalchemy import select
    import uuid
    
    token = await _register(client, db_session, "chat-lma@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 创建 thread
    tid = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]
    
    # 获取初始 last_message_at
    async with get_sessionmaker()() as db:
        thread = await db.get(Thread, uuid.UUID(tid))
        initial_lma = thread.last_message_at
    
    import asyncio
    await asyncio.sleep(0.02)
    
    # 发送聊天消息
    resp = await client.post(
        "/api/chat",
        json={"thread_id": tid, "commands": [{"type": "add-text", "text": "测试"}]},
        headers=headers
    )
    # 消费流式响应
    async for _ in resp.aiter_bytes():
        pass
    
    # 验证 last_message_at 已更新
    async with get_sessionmaker()() as db:
        await db.refresh(thread)
        assert thread.last_message_at > initial_lma, "聊天应更新 last_message_at"
```

- [ ] **Step 5: 运行聊天测试验证失败**

```bash
cd backend
pytest tests/test_chat_api.py::test_chat_updates_last_message_at -v
```

预期输出：`FAILED` （因为聊天逻辑尚未更新 last_message_at）

- [ ] **Step 6: 修改聊天接口更新 last_message_at**

修改 `backend/app/chat/router.py` 的 `chat` 函数，在接收到用户消息后、开始生成回复前，添加更新逻辑：

```python
@router.post("")
async def chat(
    request: ChatRequest,
    http_request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    thread = await _owned_thread(db, user, request.thread_id)
    from app.core.ratelimit import check_rate

    if not await check_rate(str(user.id)):
        raise HTTPException(429, "请求过于频繁")

    # 更新 last_message_at
    from datetime import UTC, datetime
    from sqlalchemy import update
    await db.execute(
        update(Thread)
        .where(Thread.id == thread.id)
        .values(last_message_at=datetime.now(UTC))
    )
    await db.commit()
    
    # ... 继续原有聊天逻辑
```

- [ ] **Step 7: 运行所有 threads 和 chat 测试**

```bash
cd backend
pytest tests/test_threads_last_message_at.py tests/test_chat_api.py::test_chat_updates_last_message_at -v
```

预期输出：`2 passed`

- [ ] **Step 8: 运行完整测试套件确保无回归**

```bash
cd backend
pytest tests/test_threads_api.py tests/test_chat_api.py -v
```

预期输出：所有测试通过

- [ ] **Step 9: Commit**

```bash
git add backend/app/threads/router.py backend/app/chat/router.py backend/tests/test_threads_last_message_at.py backend/tests/test_chat_api.py
git commit -m "feat(threads): 历史按聊天时间排序，重命名不置顶

- 列表排序改为 last_message_at DESC, created_at DESC, id DESC
- 聊天时更新 last_message_at
- 重命名只更新 updated_at
- 新增测试覆盖排序逻辑和聊天更新

Co-Authored-By: Claude <noreply@anthropic.com>"
```


---

### Task 3: 前端路由 - 支持 /chat/new 和 /chat/:threadId

**Files:**
- Modify: `frontend/src/App.tsx:35-50`
- Modify: `frontend/src/pages/ChatPage.tsx:1-152`

**Interfaces:**
- Consumes: Thread API（来自后端）
- Produces: URL 路由 `/chat/new`（草稿态）和 `/chat/:threadId`（持久化会话），ChatPage 从 URL 读取状态

- [ ] **Step 1: 编写路由测试**

创建 `frontend/src/__tests__/routing.test.tsx`:

```typescript
import { render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter, MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ChatPage from '@/pages/ChatPage';

// Mock auth store
vi.mock('@/lib/auth', () => ({
  useAuthStore: () => ({ accessToken: 'mock-token' }),
}));

// Mock API calls
vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  tryRefresh: vi.fn().mockResolvedValue(undefined),
}));

describe('Chat routing', () => {
  let qc: QueryClient;

  beforeEach(() => {
    qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  });

  it('renders draft state on /chat/new', async () => {
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/chat/new']}>
          <Routes>
            <Route path="/chat/:threadId?" element={<ChatPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.queryByText('正在准备会话…')).not.toBeInTheDocument();
    });
    // 草稿态应显示空输入框，不加载历史
  });

  it('loads thread on /chat/:threadId', async () => {
    const mockThread = { id: 'thread-123', title: '测试会话', created_at: '2026-07-31T00:00:00Z', updated_at: '2026-07-31T00:00:00Z', last_message_at: '2026-07-31T00:00:00Z' };
    
    const { apiFetch } = await import('@/lib/api');
    (apiFetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockThread,
    });

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/chat/thread-123']}>
          <Routes>
            <Route path="/chat/:threadId?" element={<ChatPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith('/api/threads/thread-123');
    });
  });
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd frontend
npm test -- src/__tests__/routing.test.tsx
```

预期输出：`FAIL` （因为路由尚未实现）

- [ ] **Step 3: 修改 App.tsx 路由配置**

修改 `frontend/src/App.tsx`，将路由改为支持可选参数：

```typescript
<Routes>
  <Route path="/login" element={<LoginPage />} />
  <Route path="/register" element={<RegisterPage />} />
  <Route
    path="/chat/:threadId?"
    element={
      <RequireAuth>
        <ChatPage />
      </RequireAuth>
    }
  />
  <Route
    path="/*"
    element={<Navigate to="/chat/new" replace />}
  />
</Routes>
```

- [ ] **Step 4: 修改 ChatPage 从 URL 读取状态**

修改 `frontend/src/pages/ChatPage.tsx`：

```typescript
import { useParams, useNavigate } from "react-router-dom";

function ChatPage() {
  const { threadId } = useParams<{ threadId?: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  
  // 草稿态：threadId === 'new' 或 undefined
  const isDraft = threadId === 'new' || threadId === undefined;
  
  // 持久化会话：threadId 是有效 UUID
  const isValidThreadId = threadId && threadId !== 'new' && /^[0-9a-f-]{36}$/.test(threadId);
  
  // 获取 thread 详情（仅当有效 threadId 时）
  const threadQuery = useQuery({
    queryKey: ['thread', threadId],
    queryFn: async () => {
      if (!isValidThreadId) return null;
      const r = await apiFetch(`/api/threads/${threadId}`);
      if (!r.ok) {
        if (r.status === 404) {
          navigate('/chat/new', { replace: true });
          throw new Error('会话不存在');
        }
        throw new Error('加载会话失败');
      }
      return r.json();
    },
    enabled: isValidThreadId,
  });
  
  // 删除自动创建空会话的逻辑（原 lines 54-75）
  
  // activeThreadId 改为从 URL 派生
  const activeThreadId = isValidThreadId ? threadId : null;
  
  // ... 其余逻辑保持不变，但不再维护独立的 activeThreadId state
}
```

- [ ] **Step 5: 运行测试**

```bash
cd frontend
npm test -- src/__tests__/routing.test.tsx
```

预期输出：`PASS`

- [ ] **Step 6: 手工验证路由**

```bash
cd frontend
npm run dev
```

访问 `http://localhost:5183/chat/new`，应显示草稿态。
访问 `http://localhost:5183/chat/<valid-thread-id>`，应加载该会话。
访问 `http://localhost:5183/chat/invalid-id-404`，应自动跳转到 `/chat/new`。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/ChatPage.tsx frontend/src/__tests__/routing.test.tsx
git commit -m "feat(frontend): URL 路由支持草稿态和会话 ID

- /chat/new 显示草稿态，不创建数据库记录
- /chat/:threadId 加载指定会话
- 404 会话自动跳转到 /chat/new
- 删除自动创建空会话逻辑

Co-Authored-By: Claude <noreply@anthropic.com>"
```


---

### Task 4: 前端首次发送 - 草稿态点击发送时创建会话并切换 URL

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx:43-152`
- Create: `frontend/src/__tests__/first-send.test.tsx`

**Interfaces:**
- Consumes: `POST /api/threads/` 创建接口、URL 路由（来自 Task 3）
- Produces: 首次发送时创建 thread、切换到 `/chat/:threadId`、防双击锁

- [ ] **Step 1: 编写首次发送测试**

创建 `frontend/src/__tests__/first-send.test.tsx`:

```typescript
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ChatPage from '@/pages/ChatPage';

vi.mock('@/lib/auth', () => ({
  useAuthStore: () => ({ accessToken: 'mock-token' }),
}));

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  tryRefresh: vi.fn().mockResolvedValue(undefined),
}));

describe('First send', () => {
  let qc: QueryClient;

  beforeEach(() => {
    qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.clearAllMocks();
  });

  it('creates thread and switches URL on first send', async () => {
    const { apiFetch } = await import('@/lib/api');
    const mockThread = { id: 'new-thread-123', title: '新对话', created_at: '2026-07-31T00:00:00Z', updated_at: '2026-07-31T00:00:00Z', last_message_at: '2026-07-31T00:00:00Z' };
    
    (apiFetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockThread,
    });

    const { container } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/chat/new']}>
          <Routes>
            <Route path="/chat/:threadId?" element={<ChatPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    // 模拟用户输入并点击发送
    const input = container.querySelector('textarea') || container.querySelector('input');
    expect(input).toBeTruthy();
    
    fireEvent.change(input!, { target: { value: '测试消息' } });
    const sendButton = screen.getByRole('button', { name: /发送|send/i });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith('/api/threads/', expect.objectContaining({
        method: 'POST',
      }));
    });
    
    // URL 应切换到新 thread ID
    expect(window.location.pathname).toBe('/chat/new-thread-123');
  });

  it('prevents double creation on rapid clicks', async () => {
    const { apiFetch } = await import('@/lib/api');
    (apiFetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ id: 'thread-123', title: '新对话', created_at: '2026-07-31T00:00:00Z', updated_at: '2026-07-31T00:00:00Z', last_message_at: '2026-07-31T00:00:00Z' }),
    });

    const { container } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/chat/new']}>
          <Routes>
            <Route path="/chat/:threadId?" element={<ChatPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    const input = container.querySelector('textarea') || container.querySelector('input');
    fireEvent.change(input!, { target: { value: '测试' } });
    
    const sendButton = screen.getByRole('button', { name: /发送|send/i });
    
    // 快速点击两次
    fireEvent.click(sendButton);
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledTimes(1); // 只创建一次
    });
  });
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd frontend
npm test -- src/__tests__/first-send.test.tsx
```

预期输出：`FAIL` （因为首次发送逻辑尚未实现）

- [ ] **Step 3: 实现首次发送逻辑**

在 `frontend/src/pages/ChatPage.tsx` 中添加首次发送处理：

```typescript
function ChatPage() {
  const { threadId } = useParams<{ threadId?: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  
  const [isSending, setIsSending] = useState(false);
  const [pendingMessage, setPendingMessage] = useState<string>('');
  
  const isDraft = threadId === 'new' || threadId === undefined;
  const isValidThreadId = threadId && threadId !== 'new' && /^[0-9a-f-]{36}$/.test(threadId);
  
  const createThreadMutation = useMutation({
    mutationFn: async () => {
      const r = await apiFetch('/api/threads/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!r.ok) throw new Error('创建会话失败');
      return r.json();
    },
    onSuccess: (thread) => {
      qc.invalidateQueries({ queryKey: threadsKey });
      navigate(`/chat/${thread.id}`, { replace: true });
    },
  });
  
  const handleFirstSend = async (message: string) => {
    if (isSending) return; // 防双击
    setIsSending(true);
    setPendingMessage(message);
    
    try {
      await createThreadMutation.mutateAsync();
      // URL 已切换，pendingMessage 会在新 URL 下发送
    } catch (err) {
      console.error('创建会话失败', err);
      // 保留输入和错误状态，允许重试
    } finally {
      setIsSending(false);
    }
  };
  
  const handleSend = (message: string) => {
    if (isDraft) {
      handleFirstSend(message);
    } else {
      // 普通发送逻辑（已存在的 RuntimeProvider）
    }
  };
  
  // 在草稿态下，不渲染 RuntimeProvider，而是自定义发送逻辑
  // 在持久化会话下，继续使用 RuntimeProvider
  
  return (
    // ... UI 逻辑，根据 isDraft 选择渲染路径
  );
}
```

- [ ] **Step 4: 运行测试**

```bash
cd frontend
npm test -- src/__tests__/first-send.test.tsx
```

预期输出：`PASS`

- [ ] **Step 5: 手工验证首次发送**

```bash
cd frontend
npm run dev
```

访问 `/chat/new`，输入消息并点击发送，验证：
- 创建了新 thread
- URL 切换到 `/chat/<new-id>`
- 消息发送成功

快速双击发送按钮，验证只创建一个 thread。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ChatPage.tsx frontend/src/__tests__/first-send.test.tsx
git commit -m "feat(frontend): 首次发送时创建会话并切换 URL

- 草稿态点击发送先创建 thread
- 创建成功后切换到 /chat/:threadId
- 防双击锁避免重复创建
- 创建失败时保留输入和错误状态

Co-Authored-By: Claude <noreply@anthropic.com>"
```


---

### Task 5: 前端侧边栏 - 点击"+"导航到草稿态

**Files:**
- Modify: `frontend/src/chat/ThreadListSidebar.tsx:169-176`

**Interfaces:**
- Consumes: URL 路由 `/chat/new`（来自 Task 3）
- Produces: 点击"+"导航到 `/chat/new`，不调用 `POST /api/threads/`

- [ ] **Step 1: 编写侧边栏导航测试**

创建 `frontend/src/__tests__/sidebar-navigation.test.tsx`:

```typescript
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ThreadListSidebar } from '@/chat/ThreadListSidebar';

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
}));

describe('Sidebar navigation', () => {
  let qc: QueryClient;

  beforeEach(() => {
    qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.clearAllMocks();
  });

  it('navigates to /chat/new on + click without API call', async () => {
    const { apiFetch } = await import('@/lib/api');
    
    // Mock threads list
    (apiFetch as any).mockResolvedValue({
      ok: true,
      json: async () => [],
    });

    const mockNavigate = vi.fn();
    vi.mock('react-router-dom', async () => {
      const actual = await vi.importActual('react-router-dom');
      return {
        ...actual,
        useNavigate: () => mockNavigate,
      };
    });

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <ThreadListSidebar
            activeThreadId={null}
            activePanel="chat"
            onThreadSelect={() => {}}
            onPanelChange={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>
    );

    const newButton = screen.getByLabelText('新对话') || screen.getByRole('button', { name: /新对话|\+/i });
    fireEvent.click(newButton);

    // 应调用 navigate，不应调用 POST /api/threads/
    expect(mockNavigate).toHaveBeenCalledWith('/chat/new');
    expect(apiFetch).not.toHaveBeenCalledWith('/api/threads/', expect.objectContaining({ method: 'POST' }));
  });

  it('navigates to thread ID on history item click', async () => {
    const { apiFetch } = await import('@/lib/api');
    
    const mockThreads = [
      { id: 'thread-1', title: '会话1', created_at: '2026-07-31T00:00:00Z', updated_at: '2026-07-31T00:00:00Z', last_message_at: '2026-07-31T00:00:00Z' },
    ];
    
    (apiFetch as any).mockResolvedValue({
      ok: true,
      json: async () => mockThreads,
    });

    const mockNavigate = vi.fn();
    vi.mock('react-router-dom', async () => {
      const actual = await vi.importActual('react-router-dom');
      return {
        ...actual,
        useNavigate: () => mockNavigate,
      };
    });

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <ThreadListSidebar
            activeThreadId={null}
            activePanel="chat"
            onThreadSelect={() => {}}
            onPanelChange={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>
    );

    const threadItem = await screen.findByText('会话1');
    fireEvent.click(threadItem);

    expect(mockNavigate).toHaveBeenCalledWith('/chat/thread-1');
  });
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd frontend
npm test -- src/__tests__/sidebar-navigation.test.tsx
```

预期输出：`FAIL` （因为侧边栏仍调用 POST）

- [ ] **Step 3: 修改侧边栏"+"按钮逻辑**

修改 `frontend/src/chat/ThreadListSidebar.tsx`：

```typescript
import { useNavigate } from "react-router-dom";

export function ThreadListSidebar({ ... }) {
  const navigate = useNavigate();
  
  // 删除原有的 createThread mutation（lines 24-32）
  
  // 修改"+"按钮点击事件（lines 169-176）
  <button
    type="button"
    aria-label="新对话"
    className="..."
    onClick={() => navigate('/chat/new')}
  >
    <Plus className="size-4" />
  </button>
}
```

- [ ] **Step 4: 修改历史项点击事件**

在同一文件中，修改历史项点击事件：

```typescript
{threads.data?.map((t) => {
  const active = t.id === activeThreadId;
  return (
    <div
      key={t.id}
      className="..."
      onClick={() => {
        navigate(`/chat/${t.id}`);
        onThreadSelect(t.id);
      }}
    >
      {/* ... */}
    </div>
  );
})}
```

- [ ] **Step 5: 运行测试**

```bash
cd frontend
npm test -- src/__tests__/sidebar-navigation.test.tsx
```

预期输出：`PASS`

- [ ] **Step 6: 运行完整前端测试套件**

```bash
cd frontend
npm test
```

预期输出：所有测试通过

- [ ] **Step 7: 手工验证完整流程**

```bash
cd frontend
npm run dev
```

完整流程验证：
1. 点击"+"，URL 变为 `/chat/new`，显示草稿态
2. 输入消息并发送，创建 thread，URL 切换到 `/chat/<new-id>`
3. 刷新页面，恢复到该会话
4. 点击历史列表中的其他会话，URL 切换并加载该会话
5. 删除当前会话，自动跳转到 `/chat/new`

- [ ] **Step 8: Commit**

```bash
git add frontend/src/chat/ThreadListSidebar.tsx frontend/src/__tests__/sidebar-navigation.test.tsx
git commit -m "feat(frontend): 侧边栏点击+导航到草稿态

- 删除立即创建会话逻辑
- 点击+使用 navigate('/chat/new')
- 历史项点击使用 navigate('/chat/:id')
- 新增测试覆盖导航行为

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 实施完成检查清单

完成所有任务后，验证以下成功标准：

- [ ] ✅ 点击"+"进入 `/chat/new`，不产生数据库记录
- [ ] ✅ 首次发送时创建 thread 并切换到 `/chat/{id}`
- [ ] ✅ 首次消息失败时会话仍保留，可重试
- [ ] ✅ 历史列表按最近聊天时间倒序排列
- [ ] ✅ 重命名不改变历史位置
- [ ] ✅ 刷新页面恢复当前会话
- [ ] ✅ 删除当前会话后进入新对话草稿态
- [ ] ✅ 同时间戳时排序稳定
- [ ] ✅ 所有现有测试通过
- [ ] ✅ 新增测试覆盖上述场景

