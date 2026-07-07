"""从 checkpointer 读取某个 thread 的历史消息，供前端刷新后恢复聊天。

## 实证结论（langgraph 1.2.8 / langgraph-checkpoint 4.1.1 / deepagents）

- checkpointer 按 **增量** 存 channel values：最新一个 checkpoint 的
  ``channel_values`` 只含本步的 delta（实测末尾 checkpoint 的 keys 是
  ``skills_metadata / skills_load_errors / __pregel_tasks``，**没有 messages**）。
  因此不能直接读 ``aget_tuple(...).checkpoint["channel_values"]["messages"]``——
  那样恒为空。

- 正确做法是让 **已编译的图** 用其 channel 规格把跨 checkpoint 的值合并回完整
  state：``agent.aget_state(config).values["messages"]`` 可靠返回全量 BaseMessage
  列表（实测 4 条：human / ai(tool_call, content="") / tool / ai(最终文本)）。
  故这里用同一个 ``build_agent(thread_id, checkpointer)`` 挂上 checkpointer 后调
  ``aget_state``。

- 渐进披露：UI 恢复只需 human/ai 的文本轮。空 content 的 ai（纯 tool_call）与
  tool 消息一律过滤，映射为 ``{"type": "human"|"ai", "content": <text>}``。
"""

from typing import Any

from langchain_core.messages import BaseMessage

from app.agent.build import build_agent


def _text(content: Any) -> str:
    """把 BaseMessage.content 归一成纯文本：str 直接用；content-block 列表则拼接其
    text 字段（忽略非文本块）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


def _to_ui(messages: list[BaseMessage]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        t = getattr(m, "type", None)
        if t not in ("human", "ai"):
            continue
        text = _text(m.content)
        if not text:  # 纯 tool_call 的 ai（content=""）无文本可恢复，跳过
            continue
        out.append({"type": t, "content": text})
    return out


async def load_thread_messages(thread_id: str, checkpointer: Any) -> list[dict]:
    """读该 thread 最新 state 的 messages，转成前端可消费的 ``{type, content}`` 列表。

    无 checkpointer（未跑 lifespan 的进程本就无跨会话历史）或该 thread 无 checkpoint
    时返回 ``[]``。
    """
    if checkpointer is None:
        return []
    agent = build_agent(thread_id, checkpointer)
    state = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    messages = state.values.get("messages", []) if state and state.values else []
    return _to_ui(messages)
