import pytest
from sqlalchemy import select

from app.credits import service
from app.credits.models import CreditTransaction
from app.skills import seed
from app.skills.models import Skill, UserSkill
from app.skills.usage import extract_used_skills
from tests.conftest import _auth, _chat_body


class _SkillReadingAgent:
    """假 agent：astream 产出一条 read_file(dyp-ask) 工具调用消息。

    append_langgraph_event 对 "updates" 事件的 messages 通道显式跳过（见 site-packages
    langgraph.py），故必须走 "messages" 流模式：payload=(msg, metadata)，model_dump 后
    tool_calls 落进 controller.state["messages"]。
    """

    async def astream(self, *a, **k):
        from langchain_core.messages import AIMessage
        msg = AIMessage(content="", tool_calls=[
            {"name": "read_file", "args": {"file_path": "skills/dyp-ask/SKILL.md"}, "id": "t1"},
        ])
        yield ((), "messages", (msg, {}))


class _SilentAgent:
    """假 agent：不读任何 skill（仅产出普通文本），用于验证回传态不被重复计费。"""

    async def astream(self, *a, **k):
        from langchain_core.messages import AIMessage
        yield ((), "messages", (AIMessage(content="ok"), {}))


async def _install_skill(db, user_id, slug: str) -> None:
    # 幂等：注册时 is_default 技能已自动安装（DB 跨用例不回滚），重复插入会撞 uq_user_skill。
    s = (await db.execute(select(Skill).where(Skill.slug == slug))).scalar_one()
    exists = (await db.execute(select(UserSkill).where(
        UserSkill.user_id == user_id, UserSkill.skill_id == s.id
    ))).scalar_one_or_none()
    if exists is None:
        db.add(UserSkill(user_id=user_id, skill_id=s.id))
        await db.commit()


async def _skill_txs(db, user_id):
    db.expire_all()
    return (await db.execute(
        select(CreditTransaction).where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.kind == "skill",
        )
    )).scalars().all()


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
    await _install_skill(db_session, registered_user.id, "dyp-ask")

    import app.chat.router as router_mod
    monkeypatch.setattr(router_mod, "build_agent", lambda *a, **k: _SkillReadingAgent())

    before = await service.get_balance(db_session, registered_user.id)
    r = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert r.status_code == 200
    await r.aread()
    txs = await _skill_txs(db_session, registered_user.id)
    assert len(txs) == 1 and txs[0].amount == -3 and txs[0].ref_id == "dyp-ask"
    after = await service.get_balance(db_session, registered_user.id)
    assert after <= before - 3


@pytest.mark.asyncio
async def test_echoed_state_does_not_recharge_skill(
    client, db_session, registered_user, a_thread, monkeypatch
):
    """C1 回归：assistant-transport 客户端每轮回传累积态。turn-2 的 state 已含 turn-1
    的 read_file tool_call。只能对本轮新消息计费，同一 user+slug 全程恰好扣一次。"""
    await seed.upsert_skills(db_session)
    s = (await db_session.execute(select(Skill).where(Skill.slug == "dyp-ask"))).scalar_one()
    s.price = 3
    await db_session.commit()
    await _install_skill(db_session, registered_user.id, "dyp-ask")

    import app.chat.router as router_mod

    # turn 1：真读了 skill，扣一次。
    monkeypatch.setattr(router_mod, "build_agent", lambda *a, **k: _SkillReadingAgent())
    r1 = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert r1.status_code == 200
    await r1.aread()
    assert len(await _skill_txs(db_session, registered_user.id)) == 1

    # turn 2：客户端回传含 turn-1 read_file 的累积态；本轮 agent 不再读 skill。
    echoed_state = {
        "messages": [
            {"type": "human", "content": "茅台现在多少钱"},
            {"type": "ai", "content": "", "tool_calls": [
                {"name": "read_file", "args": {"file_path": "skills/dyp-ask/SKILL.md"}, "id": "t1"},
            ]},
        ]
    }
    monkeypatch.setattr(router_mod, "build_agent", lambda *a, **k: _SilentAgent())
    r2 = await client.post(
        "/api/chat",
        json=_chat_body(a_thread, text="再看看", state=echoed_state),
        headers=_auth(registered_user),
    )
    assert r2.status_code == 200
    await r2.aread()

    # 回传态里的旧 read_file 不得二次计费：全程仍恰好一条 skill 流水。
    txs = await _skill_txs(db_session, registered_user.id)
    assert len(txs) == 1 and txs[0].ref_id == "dyp-ask"


@pytest.mark.asyncio
async def test_non_installed_skill_read_not_charged(
    client, db_session, registered_user, a_thread, monkeypatch
):
    """I1：agent 读了未为该用户物化的 skill（越权/幻觉/自写路径）——不得计费。"""
    await seed.upsert_skills(db_session)
    s = (await db_session.execute(select(Skill).where(Skill.slug == "dyp-ask"))).scalar_one()
    s.price = 3
    await db_session.commit()
    # 故意不安装 dyp-ask；并强制 load_installed_skills 返回空物化集。
    # router 内部按调用时 `from app.skills.materialize import load_installed_skills`，
    # 故须打补丁到源模块属性。
    import app.chat.router as router_mod
    import app.skills.materialize as mat_mod

    async def _no_skills(*a, **k):
        return []

    monkeypatch.setattr(mat_mod, "load_installed_skills", _no_skills)
    monkeypatch.setattr(router_mod, "build_agent", lambda *a, **k: _SkillReadingAgent())

    r = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert r.status_code == 200
    await r.aread()
    assert len(await _skill_txs(db_session, registered_user.id)) == 0
