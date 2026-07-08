import uuid

from langchain_core.tools import tool

from app.kb.retrieval import accessible_kb_ids, search_chunks


def make_kb_search(session_factory, user_id: uuid.UUID, kb_ids: list[uuid.UUID]):
    @tool
    async def kb_search(query: str) -> str:
        """在用户挂载的知识库中检索相关片段，返回带出处的内容。适合查已上传的研报/资料。"""
        # tool_guard(safe.py) 仅包同步函数（def wrapper，直接 return fn(...) 不 await），
        # 套在 async 工具上会返回未 await 的协程且异常永不进 try/except。故此处不套 tool_guard，
        # 改在函数体内 try/except 返回错误字符串，绝不向 agent 循环抛异常。
        try:
            async with session_factory() as db:
                allowed = await accessible_kb_ids(db, user_id, kb_ids)
                if not allowed:
                    return "（未挂载可用知识库）"
                hits = await search_chunks(db, allowed, query)
            if not hits:
                return "（知识库中未检索到相关内容）"
            return "\n\n".join(
                f"[出处：{h['filename']}]\n{h['content']}" for h in hits
            )
        except Exception as exc:  # noqa: BLE001
            return f"错误：知识库检索失败（{type(exc).__name__}: {exc}）。请换用其他工具或如实告知用户。"

    return kb_search
