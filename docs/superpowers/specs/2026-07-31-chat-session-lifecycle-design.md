# 会话生命周期修复设计

**日期**: 2026-07-31  
**状态**: 待审阅

## 问题

当前会话模块存在三个相关行为问题：

1. **点击"+"会创建新对话但未跳转**：用户点击新建按钮后，UI 没有明确切换到新对话视图，容易误以为点击未生效。
2. **空白新对话不应进入历史记录**：点击"+"会立即调用 `POST /api/threads/` 并持久化空白会话，导致历史列表积累大量从未输入内容的垃圾记录。
3. **历史记录应按最近聊天时间倒序排列**：当前按 `updated_at DESC` 排序，但重命名操作也会更新该字段，导致重命名会把会话置顶，不符合"按聊天活跃度排序"的用户预期。

## 根因分析

### 当前实现

- **前端**：
  - `ThreadListSidebar` 点击"+"时立即调用 `POST /api/threads/`（`frontend/src/chat/ThreadListSidebar.tsx:24-32,169-176`）
  - `ChatPage` 在列表为空时自动创建会话，删除最后一条后再次创建（`frontend/src/pages/ChatPage.tsx:54-75`）
  - 当前会话 ID 仅存于 React state，URL 不承载 thread ID（`frontend/src/pages/ChatPage.tsx:43-48`）
  - 点击"+"或选择历史项都不触发路由跳转，只更新 state
  - 刷新页面固定选择后端列表第一条（`updated_at DESC`），无法恢复刷新前选中的会话

- **后端**：
  - 列表接口固定返回 `updated_at DESC`（`backend/app/threads/router.py:46-59`）
  - 重命名和聊天完成都会推进 `updated_at`（`backend/app/threads/router.py:82-93`）
  - 没有独立的"最近聊天时间"字段
  - 没有稳定的二级排序键

### 约束

- 用户要求：点击发送时立即创建会话，即使消息发送失败也保留会话，允许后续重试
- 历史排序语义：按最近聊天时间倒序，重命名不应影响排序位置
- 现有测试覆盖 CRUD、标题、历史恢复、所有权和 `updated_at` 排序，但未覆盖懒持久化、URL 恢复、并发首发和稳定排序
- 主工作区 `backend/app/chat/router.py` 有未提交的 Skill Router 改动，不能在此次修复中引入冲突

## 设计方案

### 方案选择

**方案 A（推荐）**：前端草稿态 + URL 路由 + 独立 `last_message_at` 字段

- 点击"+"进入 `/chat/new`，只创建本地草稿，不调用后端
- 首次点击发送时：创建 thread → 替换 URL 为 `/chat/{threadId}` → 发送首条消息
- 消息失败时 thread 已存在，保留输入和错误状态，允许重试
- 新增 `last_message_at`，历史按它倒序排列；重命名只更新 `updated_at`

优点：符合全部语义，改动边界清楚，不必改造聊天流协议。  
缺点：首次发送比普通发送多一次创建请求，需防止双击造成重复创建。

**方案 B**：后端提供"创建并发送"接口，首次消息通过新接口完成创建和聊天，再把 thread ID 随流返回。

缺点：需改造流式协议、错误恢复和 thread ID 传递；为了让发送失败时仍保留会话，后端仍须先提交 thread，事务上并不比方案 A 更原子。

**方案 C**：继续点击"+"立即创建，但历史列表过滤空会话。

缺点：数据库仍积累垃圾空会话；刷新、反复点击"+"和跨设备状态都更复杂，不符合"未输入不应成为历史"的本质要求。

**选择方案 A**。

### 架构设计

#### 1. 会话与路由

**URL 成为当前会话的唯一真源：**

- `/chat/new`：未持久化草稿态
- `/chat/{threadId}`：已持久化会话
- 点击历史项使用 `navigate("/chat/{id}")`
- 点击"+"使用 `navigate("/chat/new")`
- 刷新和浏览器前进/后退都根据 URL 恢复会话
- 如果访问的 thread 不存在或已删除，回退到 `/chat/new`

不再维持独立的 `activeThreadId` 推断逻辑，避免 URL、React state 和 React Query 三方不一致。

#### 2. 首次发送

在 `/chat/new` 点击发送时：

1. **锁定首次发送操作**，防止双击。
2. **创建 thread**：`POST /api/threads/` 返回新 thread ID。
3. **创建成功后立即替换 URL** 为 `/chat/{id}`（使用 `navigate(..., { replace: true })`，避免在浏览器历史中留下 `/chat/new` 记录）。
4. **用新 ID 发送用户刚才输入的消息**。
5. **消息失败时保留 thread**、输入内容和错误状态，用户可重试。
6. **如果 thread 创建本身失败**，则仍停留 `/chat/new`，不发送消息，也不产生历史记录。

#### 3. 历史排序

**数据模型变更**：

给 `Thread` 增加独立字段 `last_message_at: datetime`。

**排序规则**：

- Thread 创建时设置为创建时间，因此首次发送失败的会话仍会显示在顶部。
- 每次聊天请求被接受时更新（在 `/api/chat` 接收到用户消息、准备开始生成回复时更新）。
- 重命名只更新 `updated_at`，不更新 `last_message_at`。
- 列表固定按以下顺序排序：
  1. `last_message_at DESC`（主排序：最近聊天时间）
  2. `created_at DESC`（二级排序：创建时间）
  3. `id DESC`（三级排序：数据库主键，保证完全确定性）

二级和三级排序保证时间戳相同时顺序稳定。

#### 4. 删除与草稿

- 删除当前持久化会话后进入 `/chat/new`。
- 删除最后一个历史会话后不再自动创建数据库记录。
- 在 `/chat/new` 再次点击"+"时保持当前草稿，不重复创建或导航。
- 空草稿永远不出现在历史列表中。

### 组件与数据流

#### 前端变更

**1. 路由配置**（`frontend/src/App.tsx` 或路由定义文件）

```typescript
// 新增路由参数支持
<Route path="/chat/:threadId?" element={<ChatPage />} />
// 其中 threadId 为可选，/chat 和 /chat/new 都映射到 ChatPage
```

**2. ChatPage**（`frontend/src/pages/ChatPage.tsx`）

- 从 `useParams()` 读取 `threadId`
- 如果 `threadId === 'new'` 或 `threadId === undefined`，进入**草稿态**：
  - 不调用后端创建 thread
  - 本地维护草稿输入
  - 发送按钮触发首次发送流程
- 如果 `threadId` 是有效 UUID：
  - 使用 React Query 获取 thread 详情
  - 如果 404，`navigate("/chat/new", { replace: true })`
  - 正常加载历史消息和 RuntimeProvider
- 删除自动创建空会话的逻辑

**3. ThreadListSidebar**（`frontend/src/chat/ThreadListSidebar.tsx`）

- 点击"+"时：`navigate("/chat/new")`，不再调用 `POST /api/threads/`
- 点击历史项时：`navigate("/chat/{id}")`
- 当前选中状态通过 `useParams()` 与 URL 对齐

**4. 首次发送处理**（`ChatPage` 或独立 hook）

```typescript
const handleFirstSend = async (message: string) => {
  if (isSending) return; // 防双击
  setIsSending(true);
  try {
    const thread = await createThread(); // POST /api/threads/
    navigate(`/chat/${thread.id}`, { replace: true }); // 替换 URL
    await sendMessage(thread.id, message); // 发送首条消息
  } catch (err) {
    // 如果是 thread 创建失败，停留 /chat/new
    // 如果是消息发送失败，thread 已存在，保留错误状态
  } finally {
    setIsSending(false);
  }
};
```

#### 后端变更

**1. 数据库迁移**（`backend/alembic/versions/`）

```python
# 新增字段
op.add_column('threads', sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True))

# 数据迁移：将现有 threads 的 last_message_at 初始化为 updated_at
op.execute("UPDATE threads SET last_message_at = updated_at WHERE last_message_at IS NULL")

# 设置为非空
op.alter_column('threads', 'last_message_at', nullable=False)

# 新增索引
op.create_index('ix_threads_last_message_at', 'threads', ['last_message_at'], unique=False)
```

**2. Thread 模型**（`backend/app/threads/models.py`）

```python
class Thread(Base):
    # ... 现有字段 ...
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        index=True,
        default=lambda: datetime.now(timezone.utc)
    )
```

**3. 列表接口**（`backend/app/threads/router.py`）

```python
# 修改排序
stmt = (
    select(Thread)
    .where(Thread.user_id == current_user.id)
    .order_by(
        Thread.last_message_at.desc(),
        Thread.created_at.desc(),
        Thread.id.desc()
    )
)
```

**4. 聊天接口**（`backend/app/chat/router.py`）

在接收到用户消息、准备开始生成回复时，更新 `last_message_at`：

```python
async def chat_stream(...):
    # ... 现有逻辑 ...
    
    # 接收到用户消息后，更新 last_message_at
    await db.execute(
        update(Thread)
        .where(Thread.id == thread_id, Thread.user_id == current_user.id)
        .values(last_message_at=datetime.now(timezone.utc))
    )
    await db.commit()
    
    # ... 继续生成回复 ...
```

注意：不更新 `updated_at`，保留其"最近修改时间"语义（包括重命名等元数据变更）。

**5. 重命名接口**（`backend/app/threads/router.py`）

保持现有逻辑，只更新 `updated_at`，不更新 `last_message_at`。

### 错误处理

1. **Thread 创建失败**：
   - 前端停留在 `/chat/new`
   - 显示错误提示
   - 保留用户输入，允许重试

2. **首条消息发送失败**：
   - Thread 已创建，URL 已切换到 `/chat/{id}`
   - 显示错误提示
   - 保留输入框内容和错误状态
   - 用户可点击重试，此时作为普通消息发送，不再创建新 thread

3. **访问不存在的 thread**：
   - 前端检测 404
   - 自动 `navigate("/chat/new", { replace: true })`
   - 显示友好提示："该会话已被删除"

4. **并发首次发送**（快速双击）：
   - 使用 `isSending` 状态锁，第二次点击直接返回
   - 或使用 React Query 的 `mutate` 自带去重

### 测试策略

#### 前端测试

1. **点击"+"不发出创建请求**，URL 变为 `/chat/new`
2. **首次发送只创建一个 thread**，验证网络请求数量
3. **快速双击发送不会创建两条 thread**
4. **首次消息发送失败后 thread 仍在历史中**，可再次发送
5. **刷新、前进、后退恢复 URL 对应的会话**
6. **删除当前会话后进入 `/chat/new`**
7. **历史列表选中状态与 URL 同步**

#### 后端测试

1. **重命名不会改变 `last_message_at`**
2. **发送消息会更新 `last_message_at`**
3. **列表按 `last_message_at DESC, created_at DESC, id DESC` 排序**
4. **同时间戳时排序稳定**（创建多个相同 `last_message_at` 的 threads，多次查询顺序一致）
5. **数据迁移正确初始化现有 threads 的 `last_message_at`**

#### 集成测试

1. **完整流程**：点击"+" → 输入消息 → 发送 → 验证 URL、历史列表、排序
2. **错误恢复**：首条消息失败 → 重试 → 成功
3. **多会话切换**：新建多个会话 → 在不同会话间切换 → 刷新 → 验证当前会话
4. **删除边界**：删除所有会话 → 验证不自动创建 → 点击"+" → 发送 → 验证只创建一个

### 迁移与回滚

#### 数据迁移

1. **新增 `last_message_at` 字段**，初始化为 `updated_at`
2. **新增索引** `ix_threads_last_message_at`
3. **验证现有数据**：所有 threads 的 `last_message_at` 均非空

#### 向后兼容

- API 响应中增加 `last_message_at` 字段，旧客户端可忽略
- 排序逻辑变更不影响 API 契约

#### 回滚计划

如果发现严重问题需要回滚：

1. **前端回滚**：恢复点击"+"立即创建 thread 的逻辑
2. **后端回滚**：恢复按 `updated_at DESC` 排序
3. **数据库回滚**（可选）：删除 `last_message_at` 字段和索引（但保留数据不会造成问题）

### 实现顺序

1. **后端数据库迁移和模型变更**
2. **后端列表排序和聊天接口更新**
3. **后端测试**
4. **前端路由和 ChatPage 草稿态**
5. **前端首次发送逻辑**
6. **前端 ThreadListSidebar 导航变更**
7. **前端测试**
8. **集成测试和手工验证**

### 非目标

以下不在本次修复范围内：

- 跨设备会话同步
- 会话收藏或固定功能
- 会话分组或标签
- 会话搜索优化
- 并发编辑冲突解决
- 多用户协作会话

## 风险与缓解

1. **首次发送需要两次请求（创建 + 发送）**：
   - 风险：延迟增加
   - 缓解：创建 thread 接口极轻量，通常 <50ms；两次请求总延迟仍优于用户体验改进收益

2. **URL 路由变更可能影响现有书签或分享链接**：
   - 风险：旧书签失效
   - 缓解：当前 URL 不承载 thread ID，无现有书签；新设计后 URL 才真正可分享

3. **数据库迁移需要锁表**：
   - 风险：迁移期间短暂不可用
   - 缓解：`last_message_at` 字段添加和数据初始化在低流量时段执行；索引创建可使用 `CONCURRENTLY`（PostgreSQL）

4. **并发首次发送可能创建多个 thread**：
   - 风险：快速双击创建重复会话
   - 缓解：前端锁定 `isSending` 状态；React Query `mutate` 自带去重

## 成功标准

1. ✅ 点击"+"进入 `/chat/new`，不产生数据库记录
2. ✅ 首次发送时创建 thread 并切换到 `/chat/{id}`
3. ✅ 首次消息失败时会话仍保留，可重试
4. ✅ 历史列表按最近聊天时间倒序排列
5. ✅ 重命名不改变历史位置
6. ✅ 刷新页面恢复当前会话
7. ✅ 删除当前会话后进入新对话草稿态
8. ✅ 同时间戳时排序稳定
9. ✅ 所有现有测试通过
10. ✅ 新增测试覆盖上述场景
