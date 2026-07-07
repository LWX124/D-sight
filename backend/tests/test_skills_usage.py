import pytest
from sqlalchemy import select

from app.credits import service
from app.credits.models import CreditTransaction
from app.skills import seed
from app.skills.models import Skill
from app.skills.usage import extract_used_skills
from tests.conftest import _auth, _chat_body


def test_extracts_skill_reads():
    messages = [
        {"type": "ai", "tool_calls": [
            {"name": "read_file", "args": {"file_path": "/x/ws/skills/dyp-ask/SKILL.md"}, "id": "1"},
            {"name": "read_file", "args": {"file_path": "skills/earnings-review/SKILL.md"}, "id": "2"},
            {"name": "read_file", "args": {"file_path": "tools/report_audit.py"}, "id": "3"},
            {"name": "web_search", "args": {"query": "skills/fake/SKILL.md"}, "id": "4"},
        ]},
        {"type": "tool", "content": "..."},
        "非字典消息容忍",
    ]
    assert extract_used_skills(messages) == {"dyp-ask", "earnings-review"}


def test_empty_and_malformed():
    assert extract_used_skills([]) == set()
    assert extract_used_skills([{"tool_calls": [{"name": "read_file"}]}]) == set()


@pytest.mark.asyncio
async def test_chat_charges_skill_price(client, db_session, registered_user, a_thread, monkeypatch):
    await seed.upsert_skills(db_session)
    s = (await db_session.execute(select(Skill).where(Skill.slug == "dyp-ask"))).scalar_one()
    s.price = 3
    await db_session.commit()

    # 造一个 astream 产出 read_file 工具调用消息的假 agent。
    # append_langgraph_event 对 "updates" 事件的 messages 通道显式跳过（见 site-packages
    # langgraph.py），故必须走 "messages" 流模式：payload=(msg, metadata)，model_dump 后
    # tool_calls 落进 controller.state["messages"]。
    class _SkillReadingAgent:
        async def astream(self, *a, **k):
            from langchain_core.messages import AIMessage
            msg = AIMessage(content="", tool_calls=[
                {"name": "read_file", "args": {"file_path": "skills/dyp-ask/SKILL.md"}, "id": "t1"},
            ])
            yield ((), "messages", (msg, {}))

    import app.chat.router as router_mod
    monkeypatch.setattr(router_mod, "build_agent", lambda *a, **k: _SkillReadingAgent())

    before = await service.get_balance(db_session, registered_user.id)
    r = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert r.status_code == 200
    await r.aread()
    db_session.expire_all()
    txs = (await db_session.execute(
        select(CreditTransaction).where(
            CreditTransaction.user_id == registered_user.id,
            CreditTransaction.kind == "skill",
        )
    )).scalars().all()
    assert len(txs) == 1 and txs[0].amount == -3 and txs[0].ref_id == "dyp-ask"
    after = await service.get_balance(db_session, registered_user.id)
    assert after <= before - 3
