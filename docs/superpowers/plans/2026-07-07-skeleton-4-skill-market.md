# 骨架计划 4：skill 市场 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** skill 从文件资产升级为数据库实体：市场页（列表/详情/安装/卸载）、按用户已安装 skill 组装 agent、skill 使用检测 + 固定价扣费、admin 上架/下架，打通 spec §4.1/4.2/4.3-步骤1&5/7.3 的 skill 部分。

**Architecture:** 新增 `skills` 模块（models/router/service/seed）。19 个官方 skill 由种子脚本从 `skills_data/skills/` 解析入库（幂等 upsert），注册时自动安装默认 skill（老用户由种子脚本补装，吸取计划 3 backfill 教训）。聊天组装时把该用户已安装且上架的 skill 正文物化到 thread 工作区 `skills/` 目录（清空重写，卸载即时生效）。skill 使用检测走协议层：运行结束后扫描累积消息中的 `read_file` 工具调用，路径匹配 `skills/{slug}/SKILL.md` 视为使用，按 skill 定价一次性扣费（每 run 每 skill 至多一次），写 `kind="skill"` 流水。

**Tech Stack:** FastAPI、SQLAlchemy 2 async、Alembic、现有 credits service（行锁记账）、React + TanStack Query（市场页）。

## Global Constraints

- Python 3.12 / uv / pytest + testcontainers（ryuk flaky → `TESTCONTAINERS_RYUK_DISABLED=true`）。
- 一切积分变更走 `app/credits/service.py` 记账函数（行锁）；skill 扣费新增 `kind="skill"`（`ref_type="skill"`, `ref_id=slug`）。
- skill 定价默认 **0（免费）**——机制先行，运营后定价；`price=0` 不产生扣费与流水。
- **model_weight 只存不路由**：组装时无法预知本轮命中哪个 skill，动态 flash/pro 路由显式延后（记入延后清单）；`deepseek_model` 仍由 Settings 决定。
- 沙箱纵深不放松：物化仍写入 thread 工作区内（`{ws}/skills/`），`SandboxedFilesystemBackend` 零改动。
- alembic autogenerate 已有 `include_object` 过滤 checkpoint 表——新迁移生成后仍须人工 Read 确认。
- 分支 `skeleton-4` 从 `main` 起；本地 commit 已授权，不 push（等用户 `c&p`）。
- 事实：19 个 skill 每个只有单一 SKILL.md（frontmatter: name/description），无附属文件；`skill_files` 表按 spec 建（承接未来附属文件），本期为空。
- 前端约定：API 走 `apiFetch`（自动 401 刷新）；市场页元素带 `data-testid` 便于 e2e。

---

### Task 0: 分支与骨架

**Files:**
- Create: `backend/app/skills/__init__.py`

- [ ] **Step 1: 建分支 + 空包**

```bash
cd /Users/weixi1/Documents/mine/D-sight && git checkout main && git checkout -b skeleton-4
mkdir -p backend/app/skills && touch backend/app/skills/__init__.py
git add backend/app/skills/__init__.py
git commit -m "chore(skills): scaffold skills package"
```

---

### Task 1: skill 数据模型 + 迁移

**Files:**
- Create: `backend/app/skills/models.py`
- Modify: `backend/alembic/env.py`（导入新模型）
- Create: migration（autogenerate）
- Test: `backend/tests/test_skills_models.py`

**Interfaces:**
- Produces:
  - `Skill(id: UUID, slug: str unique, name: str, description: str, category: str, version: str, body: str, tools: list(JSONB), model_weight: str, price: int, is_default: bool, is_active: bool, created_at, updated_at)`
  - `SkillFile(id: UUID, skill_id: UUID FK CASCADE, path: str, content: str, created_at)`
  - `UserSkill(id: UUID, user_id: UUID FK CASCADE, skill_id: UUID FK CASCADE, created_at)`，`UniqueConstraint(user_id, skill_id)`

- [ ] **Step 1: 写模型**

`backend/app/skills/models.py`:
```python
import datetime as dt
import uuid

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="research")
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    body: Mapped[str] = mapped_column(Text, nullable=False)  # SKILL.md 正文（含 frontmatter）
    tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model_weight: Mapped[str] = mapped_column(String(8), nullable=False, default="flash")  # flash/pro，只存不路由
    price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SkillFile(Base):
    __tablename__ = "skill_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSkill(Base):
    __tablename__ = "user_skills"
    __table_args__ = (UniqueConstraint("user_id", "skill_id", name="uq_user_skill"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: alembic 发现 + 生成迁移**

`backend/alembic/env.py` 在既有模型导入处加 `from app.skills import models as skill_models  # noqa: F401`。

Run:
```bash
cd backend && uv run alembic revision --autogenerate -m "skills"
```
Expected: 新迁移含 `create_table('skills'/'skill_files'/'user_skills')` + uq/索引；Read 确认无多余 DROP（include_object 已过滤 checkpoint，但仍人工确认）。

- [ ] **Step 3: 往返测试**

`backend/tests/test_skills_models.py`:
```python
import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.skills.models import Skill, UserSkill


@pytest.mark.asyncio
async def test_skill_and_install_roundtrip(db_session):
    s = Skill(slug=f"t-{uuid.uuid4().hex[:8]}", name="测试技能", body="---\nname: t\n---\n正文")
    u = User(email=f"sk-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add_all([s, u])
    await db_session.flush()
    db_session.add(UserSkill(user_id=u.id, skill_id=s.id))
    await db_session.commit()
    got = await db_session.get(Skill, s.id)
    assert got.price == 0 and got.is_active and got.model_weight == "flash"


@pytest.mark.asyncio
async def test_duplicate_install_rejected(db_session):
    from sqlalchemy.exc import IntegrityError
    s = Skill(slug=f"d-{uuid.uuid4().hex[:8]}", name="d", body="b")
    u = User(email=f"dup-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add_all([s, u])
    await db_session.flush()
    db_session.add(UserSkill(user_id=u.id, skill_id=s.id))
    await db_session.flush()
    db_session.add(UserSkill(user_id=u.id, skill_id=s.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
```

- [ ] **Step 4: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skills_models.py -q`
Expected: 2 passed

```bash
git add backend/app/skills/models.py backend/alembic/ backend/tests/test_skills_models.py
git commit -m "feat(skills): skill/skill_file/user_skill models and migration"
```

---

### Task 2: 种子导入 + 注册自动安装

**Files:**
- Create: `backend/app/skills/seed.py`
- Create: `backend/scripts/seed_skills.py`
- Modify: `backend/app/auth/service.py`（注册钩子）
- Test: `backend/tests/test_skills_seed.py`

**Interfaces:**
- Consumes: `Skill`/`UserSkill`（Task 1）、`skills_data/skills/{slug}/SKILL.md`（19 个，frontmatter 含 name/description）。
- Produces:
  - `seed.parse_skill_md(text: str, slug: str) -> dict`（返回 name/description/body；frontmatter 缺失时 name=slug）
  - `async def seed.upsert_skills(db) -> int`（扫描 SKILLS_DATA/skills，按 slug upsert：新建或更新 body/name/description；不覆盖运营字段 price/is_active/is_default/model_weight/category；PRO_SLUGS = {"investment-research", "deep-company-series"} 首建时 model_weight="pro"；返回处理数）
  - `async def seed.install_defaults(db, user_id) -> int`（给用户装上所有 is_default 且 is_active 的 skill，已装跳过，返回新装数）
  - `async def seed.install_defaults_for_all_users(db) -> int`（老用户补装）
  - CLI `uv run python -m scripts.seed_skills`（upsert + 全量补装，幂等）
  - 注册流程：用户创建同事务内 `await install_defaults(db, user.id)`

- [ ] **Step 1: seed 实现**

`backend/app/skills/seed.py`:
```python
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.workspace import SKILLS_DATA
from app.auth.models import User
from app.skills.models import Skill, UserSkill

PRO_SLUGS = {"investment-research", "deep-company-series"}
_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_skill_md(text: str, slug: str) -> dict:
    name, description = slug, ""
    m = _FM.match(text)
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"') or slug
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"')
    return {"name": name, "description": description, "body": text}


async def upsert_skills(db: AsyncSession) -> int:
    root = SKILLS_DATA / "skills"
    count = 0
    for d in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        slug = d.name
        meta = parse_skill_md((d / "SKILL.md").read_text(encoding="utf-8"), slug)
        existing = (await db.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
        if existing is None:
            db.add(Skill(
                slug=slug, name=meta["name"], description=meta["description"], body=meta["body"],
                model_weight="pro" if slug in PRO_SLUGS else "flash",
            ))
        else:  # 只刷新内容字段，运营字段（price/is_active/...）不动
            existing.name, existing.description, existing.body = meta["name"], meta["description"], meta["body"]
        count += 1
    await db.flush()
    return count


async def install_defaults(db: AsyncSession, user_id) -> int:
    skills = (await db.execute(
        select(Skill).where(Skill.is_default.is_(True), Skill.is_active.is_(True))
    )).scalars().all()
    installed = {
        us.skill_id for us in (await db.execute(
            select(UserSkill).where(UserSkill.user_id == user_id)
        )).scalars()
    }
    n = 0
    for s in skills:
        if s.id not in installed:
            db.add(UserSkill(user_id=user_id, skill_id=s.id))
            n += 1
    await db.flush()
    return n


async def install_defaults_for_all_users(db: AsyncSession) -> int:
    n = 0
    for user in (await db.execute(select(User))).scalars():
        n += await install_defaults(db, user.id)
    await db.flush()
    return n
```

- [ ] **Step 2: CLI**

`backend/scripts/seed_skills.py`:
```python
"""导入官方 skill 并给存量用户补装默认 skill（幂等）：uv run python -m scripts.seed_skills"""
import asyncio

from app.core.db import get_sessionmaker
from app.skills import seed


async def _main():
    async with get_sessionmaker()() as s:
        n_skills = await seed.upsert_skills(s)
        n_installs = await seed.install_defaults_for_all_users(s)
        await s.commit()
    print(f"skills upserted: {n_skills}, installs added: {n_installs}")


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 3: 注册钩子**

`backend/app/auth/service.py` 注册函数内，`ensure_account(db, user.id)` 调用的相邻处（同一事务、commit 前）加：
```python
    from app.skills.seed import install_defaults
    await install_defaults(db, user.id)
```

- [ ] **Step 4: 测试**

`backend/tests/test_skills_seed.py`:
```python
import pytest
from sqlalchemy import func, select

from app.skills import seed
from app.skills.models import Skill, UserSkill


def test_parse_frontmatter():
    text = '---\nname: dyp-ask\ndescription: "段永平问答"\n---\n\n# 正文'
    meta = seed.parse_skill_md(text, "dyp-ask")
    assert meta["name"] == "dyp-ask" and meta["description"] == "段永平问答"
    assert meta["body"].startswith("---")


def test_parse_missing_frontmatter_falls_back():
    meta = seed.parse_skill_md("# 无 frontmatter", "x-slug")
    assert meta["name"] == "x-slug" and meta["description"] == ""


@pytest.mark.asyncio
async def test_upsert_idempotent_and_preserves_ops_fields(db_session):
    n1 = await seed.upsert_skills(db_session)
    assert n1 == 19
    one = (await db_session.execute(select(Skill).limit(1))).scalar_one()
    one.price = 42
    one.is_active = False
    await db_session.flush()
    n2 = await seed.upsert_skills(db_session)  # 再跑不重复、不覆盖运营字段
    assert n2 == 19
    total = (await db_session.execute(select(func.count()).select_from(Skill))).scalar_one()
    assert total >= 19
    again = await db_session.get(Skill, one.id)
    assert again.price == 42 and again.is_active is False
    assert (await db_session.execute(
        select(Skill).where(Skill.slug == "investment-research")
    )).scalar_one().model_weight == "pro"
    await db_session.rollback()


@pytest.mark.asyncio
async def test_register_auto_installs_defaults(client, db_session):
    await seed.upsert_skills(db_session)
    await db_session.commit()
    import uuid as _uuid
    email = f"auto-{_uuid.uuid4()}@t.dev"
    r = await client.post("/api/auth/request-code", json={"email": email})
    code = r.json()["debug_code"]
    r2 = await client.post("/api/auth/register",
                           json={"email": email, "code": code, "password": "pw-123456"})
    assert r2.status_code in (200, 201)
    from app.auth.models import User
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    n = (await db_session.execute(
        select(func.count()).select_from(UserSkill).where(UserSkill.user_id == user.id)
    )).scalar_one()
    assert n >= 19
```
（注册测试依赖 FAKE_LLM debug_code 后门——沿用 `tests/test_auth_api.py` 的既有模式设置 FAKE_LLM env + `get_settings.cache_clear()`，以该文件实际做法为准；register 的响应码/字段以现有 auth 测试为准微调。）

- [ ] **Step 5: 跑测试 + 回归 + Commit**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skills_seed.py tests/test_auth_api.py -q`
Expected: 全绿

```bash
git add backend/app/skills/seed.py backend/scripts/seed_skills.py backend/app/auth/service.py backend/tests/test_skills_seed.py
git commit -m "feat(skills): seed importer with ops-field preservation and register auto-install"
```

---

### Task 3: 市场 API（列表/详情/安装/卸载）

**Files:**
- Create: `backend/app/skills/router.py`、`backend/app/skills/schemas.py`
- Modify: `backend/app/main.py`（挂载）
- Test: `backend/tests/test_skills_api.py`

**Interfaces:**
- Consumes: `Skill`/`UserSkill`、`get_current_user`、`seed.upsert_skills`（测试造数）。
- Produces:
  - `GET /api/skills` → `[{slug,name,description,category,price,model_weight,is_default,installed}]`（仅 is_active，按 slug 排序）
  - `GET /api/skills/{slug}` → 上述字段 + `body`（未上架/不存在 → 404）
  - `POST /api/skills/{slug}/install` → `{"installed": true}`（幂等；未上架 404）
  - `DELETE /api/skills/{slug}/install` → `{"installed": false}`（未装也 200 幂等）

- [ ] **Step 1: schemas + router**

`backend/app/skills/schemas.py`:
```python
from pydantic import BaseModel


class SkillOut(BaseModel):
    slug: str
    name: str
    description: str
    category: str
    price: int
    model_weight: str
    is_default: bool
    installed: bool


class SkillDetail(SkillOut):
    body: str
```

`backend/app/skills/router.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.skills.models import Skill, UserSkill
from app.skills.schemas import SkillDetail, SkillOut

router = APIRouter(prefix="/api/skills", tags=["skills"])


async def _active_skill(db: AsyncSession, slug: str) -> Skill:
    s = (await db.execute(
        select(Skill).where(Skill.slug == slug, Skill.is_active.is_(True))
    )).scalar_one_or_none()
    if s is None:
        raise HTTPException(404, "skill 不存在")
    return s


async def _installed_ids(db: AsyncSession, user_id) -> set:
    return {
        us.skill_id for us in (await db.execute(
            select(UserSkill).where(UserSkill.user_id == user_id)
        )).scalars()
    }


def _out(s: Skill, installed: bool) -> dict:
    return {
        "slug": s.slug, "name": s.name, "description": s.description,
        "category": s.category, "price": s.price, "model_weight": s.model_weight,
        "is_default": s.is_default, "installed": installed,
    }


@router.get("", response_model=list[SkillOut])
async def list_skills(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    skills = (await db.execute(
        select(Skill).where(Skill.is_active.is_(True)).order_by(Skill.slug)
    )).scalars().all()
    installed = await _installed_ids(db, user.id)
    return [_out(s, s.id in installed) for s in skills]


@router.get("/{slug}", response_model=SkillDetail)
async def skill_detail(slug: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await _active_skill(db, slug)
    installed = await _installed_ids(db, user.id)
    return {**_out(s, s.id in installed), "body": s.body}


@router.post("/{slug}/install")
async def install(slug: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await _active_skill(db, slug)
    if s.id not in await _installed_ids(db, user.id):
        db.add(UserSkill(user_id=user.id, skill_id=s.id))
        await db.commit()
    return {"installed": True}


@router.delete("/{slug}/install")
async def uninstall(slug: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await _active_skill(db, slug)
    for us in (await db.execute(
        select(UserSkill).where(UserSkill.user_id == user.id, UserSkill.skill_id == s.id)
    )).scalars():
        await db.delete(us)
    await db.commit()
    return {"installed": False}
```
`main.py`：`from app.skills.router import router as skills_router` + `app.include_router(skills_router)`。

- [ ] **Step 2: 测试**

`backend/tests/test_skills_api.py`:
```python
import pytest
from sqlalchemy import select

from app.skills import seed
from app.skills.models import Skill


@pytest.fixture
async def seeded(db_session):
    await seed.upsert_skills(db_session)
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_marks_installed(client, db_session, seeded, registered_user):
    r = await client.get("/api/skills", headers=_auth(registered_user))
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 19
    assert all(i["installed"] for i in items)  # 注册自动装了默认 skill


@pytest.mark.asyncio
async def test_detail_and_install_cycle(client, db_session, seeded, registered_user):
    h = _auth(registered_user)
    d = await client.get("/api/skills/dyp-ask", headers=h)
    assert d.status_code == 200 and d.json()["body"].startswith("---")
    r1 = await client.delete("/api/skills/dyp-ask/install", headers=h)
    assert r1.json() == {"installed": False}
    lst = await client.get("/api/skills", headers=h)
    assert next(i for i in lst.json() if i["slug"] == "dyp-ask")["installed"] is False
    r2 = await client.post("/api/skills/dyp-ask/install", headers=h)
    assert r2.json() == {"installed": True}
    r3 = await client.post("/api/skills/dyp-ask/install", headers=h)  # 幂等
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_inactive_hidden_and_404(client, db_session, seeded, registered_user):
    h = _auth(registered_user)
    s = (await db_session.execute(select(Skill).where(Skill.slug == "dyp-ask"))).scalar_one()
    s.is_active = False
    await db_session.commit()
    lst = await client.get("/api/skills", headers=h)
    assert all(i["slug"] != "dyp-ask" for i in lst.json())
    assert (await client.get("/api/skills/dyp-ask", headers=h)).status_code == 404
    assert (await client.post("/api/skills/dyp-ask/install", headers=h)).status_code == 404
    s.is_active = True
    await db_session.commit()
```
（`registered_user`/`_auth` 用 conftest 既有夹具；`seeded` 若与其它测试的种子冲突，按 slug upsert 本就幂等。）

- [ ] **Step 3: 跑测试 + Commit**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skills_api.py -q`
Expected: 3 passed

```bash
git add backend/app/skills/router.py backend/app/skills/schemas.py backend/app/main.py backend/tests/test_skills_api.py
git commit -m "feat(skills): market API with list/detail/install/uninstall"
```

---

### Task 4: admin 上架/下架 + 定价调整

**Files:**
- Modify: `backend/app/admin/router.py`、`backend/app/admin/schemas.py`
- Test: `backend/tests/test_admin_api.py`（追加）

**Interfaces:**
- Consumes: `require_admin`、`AdminAuditLog`、`Skill`。
- Produces:
  - `PATCH /api/admin/skills/{slug}` body `{is_active?: bool, price?: int}`（部分更新；写 `AdminAuditLog(action="skill_update", target_type="skill", target_id=slug, detail=变更字段)`；skill 不存在 404；price<0 → 400）

- [ ] **Step 1: schema + 端点**

`backend/app/admin/schemas.py` 追加:
```python
class SkillUpdate(BaseModel):
    is_active: bool | None = None
    price: int | None = None
```

`backend/app/admin/router.py` 追加（复用既有 imports 风格）:
```python
from sqlalchemy import select

from app.admin.schemas import SkillUpdate
from app.skills.models import Skill


@router.patch("/skills/{slug}")
async def update_skill(
    slug: str, body: SkillUpdate, admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    s = (await db.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
    if s is None:
        raise HTTPException(404, "skill 不存在")
    changes = {}
    if body.is_active is not None:
        s.is_active = body.is_active
        changes["is_active"] = body.is_active
    if body.price is not None:
        if body.price < 0:
            raise HTTPException(400, "价格不能为负")
        s.price = body.price
        changes["price"] = body.price
    db.add(AdminAuditLog(
        admin_id=admin.id, action="skill_update", target_type="skill", target_id=slug,
        detail=changes,
    ))
    await db.commit()
    return {"slug": s.slug, "is_active": s.is_active, "price": s.price}
```

- [ ] **Step 2: 测试（追加到 test_admin_api.py）**

```python
@pytest.mark.asyncio
async def test_admin_skill_toggle_and_price(client, db_session):
    from sqlalchemy import select as _select
    from app.credits.models import AdminAuditLog
    from app.skills import seed
    await seed.upsert_skills(db_session)
    await db_session.commit()
    admin = User(email=f"sa-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"), role="admin")
    db_session.add(admin)
    await db_session.commit()
    h = _auth(admin)
    r = await client.patch("/api/admin/skills/dyp-ask", json={"is_active": False, "price": 5}, headers=h)
    assert r.json() == {"slug": "dyp-ask", "is_active": False, "price": 5}
    audits = (await db_session.execute(
        _select(AdminAuditLog).where(AdminAuditLog.action == "skill_update",
                                     AdminAuditLog.target_id == "dyp-ask")
    )).scalars().all()
    assert audits and audits[-1].detail == {"is_active": False, "price": 5}
    assert (await client.patch("/api/admin/skills/nope", json={"price": 1}, headers=h)).status_code == 404
    assert (await client.patch("/api/admin/skills/dyp-ask", json={"price": -1}, headers=h)).status_code == 400
    # 还原，避免影响其它测试
    await client.patch("/api/admin/skills/dyp-ask", json={"is_active": True, "price": 0}, headers=h)
```

- [ ] **Step 3: 跑测试 + Commit**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_admin_api.py -q`
Expected: 全绿（含既有 2 项）

```bash
git add backend/app/admin/ backend/tests/test_admin_api.py
git commit -m "feat(admin): skill activate/price update with audit"
```

---

### Task 5: 按已安装 skill 组装 agent

**Files:**
- Create: `backend/app/skills/materialize.py`
- Modify: `backend/app/agent/build.py`（`build_agent` 加 `skill_rows` 参数）
- Modify: `backend/app/chat/router.py`（查已安装 skill 传入）
- Modify: `backend/app/agent/workspace.py`（移除创建时全量拷贝 skills——tools 拷贝保留）
- Test: `backend/tests/test_skills_materialize.py`、回归 `tests/test_workspace.py`（改动全量拷贝断言）

**Interfaces:**
- Consumes: `Skill`、`UserSkill`、`get_thread_workspace`。
- Produces:
  - `materialize.load_installed_skills(db, user_id) -> list[Skill]`（已安装 ∩ is_active）
  - `materialize.write_skills(ws: Path, rows: list) -> None`（**清空重写** `{ws}/skills/`：每 row 写 `{ws}/skills/{slug}/SKILL.md` = row.body；卸载/下架即时生效）
  - `build_agent(thread_id, checkpointer=None, skill_rows=None)`：`skill_rows is not None` → 先 `write_skills`；`None` → 兼容旧行为（用 ws/skills 现状，供 test_real_smoke 等直连调用）
  - chat 端点在 `build_agent` 前 `load_installed_skills(db, user.id)` 并传入

- [ ] **Step 1: materialize**

`backend/app/skills/materialize.py`:
```python
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.skills.models import Skill, UserSkill


async def load_installed_skills(db: AsyncSession, user_id) -> list[Skill]:
    return list((await db.execute(
        select(Skill).join(UserSkill, UserSkill.skill_id == Skill.id)
        .where(UserSkill.user_id == user_id, Skill.is_active.is_(True))
        .order_by(Skill.slug)
    )).scalars())


def write_skills(ws: Path, rows: list) -> None:
    """清空重写 {ws}/skills/：卸载与下架在下一次组装即时生效。"""
    dest = ws / "skills"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for row in rows:
        d = dest / row.slug
        d.mkdir()
        (d / "SKILL.md").write_text(row.body, encoding="utf-8")
```

- [ ] **Step 2: build_agent 接线**

`backend/app/agent/build.py`:
```python
def build_agent(thread_id: str, checkpointer=None, skill_rows=None):
    ws = get_thread_workspace(thread_id)
    if skill_rows is not None:
        from app.skills.materialize import write_skills
        write_skills(ws, skill_rows)
    ...  # 其余不变，skills=[str(ws / "skills")]
```
`skills=[str(ws / "skills")]` 需在目录不存在时也能工作：`skill_rows=None` 且 ws 无 skills 目录（新 workspace，见 Step 3）时创建空目录：
```python
    (ws / "skills").mkdir(exist_ok=True)
```
（放在 create_deep_agent 之前，无条件执行，幂等。）

- [ ] **Step 3: workspace 移除全量拷贝**

`backend/app/agent/workspace.py` `get_thread_workspace` 中删除 `shutil.copytree(SKILLS_DATA / "skills", ws / "skills")` 一行（tools 拷贝保留）。skill 内容自此一律来自 DB 物化；`test_real_smoke` 若依赖全量拷贝（Read 确认），在该测试 setup 里显式 `write_skills(ws, ...)` 或改为断言空 skills 也可跑通问题（股票问答不依赖 skill）——以实际测试内容为准最小改动。
同步更新 `tests/test_workspace.py::test_workspace_copies_skills`：断言改为「创建后 `ws/skills` 不存在（物化职责移交）」或直接删除该测试并在报告说明。

- [ ] **Step 4: chat 端点接线**

`backend/app/chat/router.py` `chat()` 中 `build_agent` 调用前：
```python
    from app.skills.materialize import load_installed_skills
    skill_rows = await load_installed_skills(db, user.id)
    agent = build_agent(thread_id, checkpointer, skill_rows=skill_rows)
```

- [ ] **Step 5: 测试**

`backend/tests/test_skills_materialize.py`:
```python
import pytest

from app.skills import seed
from app.skills.materialize import load_installed_skills, write_skills


@pytest.mark.asyncio
async def test_write_skills_clears_and_writes(tmp_path):
    class Row:
        def __init__(self, slug, body):
            self.slug, self.body = slug, body
    ws = tmp_path
    (ws / "skills" / "stale").mkdir(parents=True)
    write_skills(ws, [Row("a", "A正文"), Row("b", "B正文")])
    assert (ws / "skills" / "a" / "SKILL.md").read_text(encoding="utf-8") == "A正文"
    assert not (ws / "skills" / "stale").exists()  # 旧内容被清
    write_skills(ws, [Row("a", "A正文")])  # 卸载 b
    assert not (ws / "skills" / "b").exists()


@pytest.mark.asyncio
async def test_load_installed_excludes_inactive(db_session, registered_user):
    from sqlalchemy import select
    from app.skills.models import Skill
    await seed.upsert_skills(db_session)
    from app.skills.seed import install_defaults
    await install_defaults(db_session, registered_user.id)
    await db_session.commit()
    rows = await load_installed_skills(db_session, registered_user.id)
    assert len(rows) >= 19
    s = (await db_session.execute(select(Skill).where(Skill.slug == "dyp-ask"))).scalar_one()
    s.is_active = False
    await db_session.commit()
    rows2 = await load_installed_skills(db_session, registered_user.id)
    assert all(r.slug != "dyp-ask" for r in rows2)
    s.is_active = True
    await db_session.commit()
```

- [ ] **Step 6: 全量回归 + Commit**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q`
Expected: 全绿（含 chat 回归——FAKE_LLM 不读 skill，物化空/满皆可跑）

```bash
git add backend/app/skills/materialize.py backend/app/agent/build.py backend/app/agent/workspace.py backend/app/chat/router.py backend/tests/
git commit -m "feat(skills): assemble agent from user-installed skills via DB materialization"
```

---

### Task 6: skill 使用检测 + 固定价扣费

**Files:**
- Create: `backend/app/skills/usage.py`
- Modify: `backend/app/chat/router.py`（run 结束扫描 + 扣费）
- Test: `backend/tests/test_skills_usage.py`

**Interfaces:**
- Consumes: `controller.state["messages"]`（run 累积消息，含 AI 消息 tool_calls）、`service.charge`、`Skill.price`。
- Produces:
  - `usage.extract_used_skills(messages: list[dict]) -> set[str]`（扫描 tool_calls 中 name 为 read_file 类、参数路径匹配 `skills/{slug}/SKILL.md` 的调用，返回 slug 集合）
  - chat 端点 finally 中：对每个 used slug 查 `Skill.price`，`price>0` 则 `service.charge(s, user.id, price, kind="skill", ref_type="skill", ref_id=slug)`（每 run 每 skill 至多一次）

- [ ] **Step 1: 实证——deepagents read 工具的消息形态**

deepagents 0.6.12 的文件读工具名与参数需实证（不可凭记忆写死）。Run:
```bash
cd backend && uv run python -c "
from deepagents import create_deep_agent
a = create_deep_agent(model=None, tools=[]) if False else None
import deepagents, inspect, pkgutil
import deepagents.backends as b
print([m.name for m in pkgutil.iter_modules(deepagents.__path__)])
" 2>/dev/null || true
uv run python - <<'EOF'
# 直接从 FilesystemBackend/中间件源码 grep 工具名
import subprocess
subprocess.run(["grep", "-rn", "read_file\|file_path", ".venv/lib/python3.12/site-packages/deepagents/", "--include=*.py", "-l"])
EOF
```
再 grep 命中的文件确认：工具名（预期 `read_file`）与路径参数名（预期 `file_path`）。**以实证结果为准**写 Step 2 的匹配逻辑；把证据（文件:行）写进报告。

- [ ] **Step 2: extract_used_skills**

`backend/app/skills/usage.py`（工具名/参数名按 Step 1 实证微调）:
```python
import re

_SKILL_RE = re.compile(r"(?:^|/)skills/([^/]+)/SKILL\.md$")
_READ_TOOLS = {"read_file"}  # 以 Step 1 实证为准


def extract_used_skills(messages: list) -> set[str]:
    used: set[str] = set()
    for m in messages:
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            if tc.get("name") not in _READ_TOOLS:
                continue
            args = tc.get("args") or {}
            path = args.get("file_path") or args.get("path") or ""
            match = _SKILL_RE.search(str(path))
            if match:
                used.add(match.group(1))
    return used
```

- [ ] **Step 3: 单测（协议层合成消息）**

`backend/tests/test_skills_usage.py`:
```python
from app.skills.usage import extract_used_skills


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
```

- [ ] **Step 4: chat 端点扣费接线**

`backend/app/chat/router.py` `run_callback` 的 finally 块内、token 扣费同一 session 中追加：
```python
            from app.skills.usage import extract_used_skills
            used = extract_used_skills(controller.state.get("messages") or [])
            if used:
                from sqlalchemy import select as _select
                from app.skills.models import Skill
                rows = (await s.execute(
                    _select(Skill).where(Skill.slug.in_(used), Skill.price > 0)
                )).scalars().all()
                for skill_row in rows:
                    await service.charge(
                        s, user.id, skill_row.price,
                        kind="skill", ref_type="skill", ref_id=skill_row.slug,
                    )
```
（放在 token charge 之后、同一 `async with get_sessionmaker()() as s:` 内、`updated_at` touch 之前；失败运行（ok=False）也按已读 skill 扣——skill 已消费。）

- [ ] **Step 5: 端点级测试（追加到 test_skills_usage.py）**

```python
import pytest
from sqlalchemy import select

from app.credits import service
from app.credits.models import CreditTransaction
from app.skills import seed
from app.skills.models import Skill


@pytest.mark.asyncio
async def test_chat_charges_skill_price(client, db_session, registered_user, a_thread, monkeypatch):
    await seed.upsert_skills(db_session)
    s = (await db_session.execute(select(Skill).where(Skill.slug == "dyp-ask"))).scalar_one()
    s.price = 3
    await db_session.commit()

    # 造一个 astream 产出 read_file 工具调用消息的假 agent
    class _SkillReadingAgent:
        async def astream(self, *a, **k):
            from langchain_core.messages import AIMessage
            msg = AIMessage(content="", tool_calls=[
                {"name": "read_file", "args": {"file_path": "skills/dyp-ask/SKILL.md"}, "id": "t1"},
            ])
            yield ((), "updates", {"agent": {"messages": [msg]}})

    import app.chat.router as router_mod
    monkeypatch.setattr(router_mod, "build_agent", lambda *a, **k: _SkillReadingAgent())

    before = await service.get_balance(db_session, registered_user.id)
    r = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert r.status_code == 200
    await r.aread()
    txs = (await db_session.execute(
        select(CreditTransaction).where(
            CreditTransaction.user_id == registered_user.id,
            CreditTransaction.kind == "skill",
        )
    )).scalars().all()
    assert len(txs) == 1 and txs[0].amount == -3 and txs[0].ref_id == "dyp-ask"
    after = await service.get_balance(db_session, registered_user.id)
    assert after <= before - 3
```
（假 agent 的事件形态要能被 `append_langgraph_event` 消化并把 tool_calls 落进 `controller.state["messages"]`——以 Task 6 Step 1 与现有 test_chat_api 的事件构造为准微调；若 updates 事件不落 messages，改用 messages 模式事件元组。测试关键断言是 kind="skill" 流水，与事件形态解耦。）

- [ ] **Step 6: 跑测试 + 全量回归 + Commit**

Run: `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skills_usage.py -q && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q`
Expected: 全绿

```bash
git add backend/app/skills/usage.py backend/app/chat/router.py backend/tests/test_skills_usage.py
git commit -m "feat(skills): usage detection via read_file tool calls and fixed-price charging"
```

---

### Task 7: 前端市场页

**Files:**
- Create: `frontend/src/lib/skills.ts`、`frontend/src/pages/SkillsPage.tsx`
- Modify: 路由（`App.tsx` 或路由文件）+ 侧栏导航入口
- Test: `frontend/src/lib/skills.test.ts`

**Interfaces:**
- Consumes: `apiFetch`、后端市场 API（Task 3 形状）。
- Produces:
  - `fetchSkills(): Promise<SkillItem[]>`、`installSkill(slug)`、`uninstallSkill(slug)`（均走 apiFetch）
  - 路由 `/skills`；聊天侧栏一个「技能市场」入口链接
  - 页面：卡片列表（name/description/price 徽标/已安装态），按钮 安装/卸载（`data-testid="skill-install-{slug}"`），操作后 invalidate 列表

- [ ] **Step 1: API 封装 + 测试**

`frontend/src/lib/skills.ts`:
```ts
import { apiFetch } from "./api";

export type SkillItem = {
  slug: string; name: string; description: string; category: string;
  price: number; model_weight: string; is_default: boolean; installed: boolean;
};

export async function fetchSkills(): Promise<SkillItem[]> {
  const res = await apiFetch("/api/skills");
  if (!res.ok) throw new Error("failed to load skills");
  return res.json();
}

export async function installSkill(slug: string): Promise<void> {
  const res = await apiFetch(`/api/skills/${slug}/install`, { method: "POST" });
  if (!res.ok) throw new Error("install failed");
}

export async function uninstallSkill(slug: string): Promise<void> {
  const res = await apiFetch(`/api/skills/${slug}/install`, { method: "DELETE" });
  if (!res.ok) throw new Error("uninstall failed");
}
```

`frontend/src/lib/skills.test.ts`:
```ts
import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { fetchSkills, installSkill } from "./skills";

describe("skills api", () => {
  it("parses list", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify([{ slug: "dyp-ask", name: "n", description: "d",
        category: "research", price: 0, model_weight: "flash", is_default: true, installed: true }]),
        { status: 200 }),
    );
    const items = await fetchSkills();
    expect(items[0].slug).toBe("dyp-ask");
    expect(items[0].installed).toBe(true);
  });

  it("install posts to endpoint", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await installSkill("dyp-ask");
    expect(spy).toHaveBeenCalledWith("/api/skills/dyp-ask/install", { method: "POST" });
  });
});
```

- [ ] **Step 2: 页面 + 路由 + 导航**

`frontend/src/pages/SkillsPage.tsx`：`useQuery(["skills"], fetchSkills)` 渲染卡片栅格：name、description（截断）、`price>0` 显示「{price} 积分/次」徽标否则「免费」、`model_weight==="pro"` 显示「Pro」徽标；按钮 安装/卸载（`useMutation` → `invalidateQueries(["skills"])`），`data-testid="skill-install-{slug}"`；顶部返回聊天链接。样式复用现有 shadcn 组件（Card/Button/Badge——以 `frontend/src/components/ui/` 现有组件为准，缺则 div+现有类名，不新增组件库）。
路由：在现有 Router 中加 `/skills`（RequireAuth 包裹，与聊天页同级）。读 `frontend/src/App.tsx`（或路由定义处）与聊天侧栏组件，加「技能市场」链接（`data-testid="nav-skills"`）。

- [ ] **Step 3: 验证 + Commit**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 全绿 + 构建成功

手工冒烟（dev postgres 5434 + 先跑 `uv run python -m scripts.seed_skills`）：登录 → 侧栏进入 /skills → 看到 19 卡片全部「已安装」→ 卸载 dyp-ask → 刷新仍未安装 → 重新安装。贴观察结果。

```bash
git add frontend/src/
git commit -m "feat(frontend): skill market page with install/uninstall"
```

---

### Task 8: 集成闭环 + README

**Files:**
- Create: `backend/tests/test_skills_flow.py`
- Modify: `backend/README.md`（「skill 市场（计划 4）」一节）
- Modify: `frontend/e2e/chat.spec.ts`（追加市场页冒烟断言，best-effort）

**Interfaces:**
- 串起 Task 2/3/5/6：注册自动装 → 卸载后组装不含该 skill → 定价 skill 使用后产生 kind="skill" 流水。

- [ ] **Step 1: 集成测试**

`backend/tests/test_skills_flow.py`:
```python
import pytest
from sqlalchemy import select

from app.skills import seed
from app.skills.materialize import load_installed_skills


@pytest.mark.asyncio
async def test_uninstall_excludes_from_assembly(client, db_session, registered_user):
    await seed.upsert_skills(db_session)
    from app.skills.seed import install_defaults
    await install_defaults(db_session, registered_user.id)
    await db_session.commit()
    h = _auth(registered_user)
    rows = await load_installed_skills(db_session, registered_user.id)
    assert any(r.slug == "dyp-ask" for r in rows)
    await client.delete("/api/skills/dyp-ask/install", headers=h)
    rows2 = await load_installed_skills(db_session, registered_user.id)
    assert all(r.slug != "dyp-ask" for r in rows2)
    # 物化落盘验证
    import uuid as _uuid
    from app.agent.workspace import get_thread_workspace
    from app.skills.materialize import write_skills
    tid = str(_uuid.uuid4())
    ws = get_thread_workspace(tid)
    write_skills(ws, rows2)
    assert not (ws / "skills" / "dyp-ask").exists()
    assert (ws / "skills" / "earnings-review" / "SKILL.md").exists()
```

- [ ] **Step 2: e2e 市场页冒烟（best-effort）**

`frontend/e2e/chat.spec.ts` 追加（或新 spec）：登录后访问 `/skills`，断言 `[data-testid="skill-install-dyp-ask"]` 可见。跑 `npx playwright test`；若环境性 flaky 超出 selector 微调，回退该改动并在报告注明（后端集成测试是必交付物）。注意 e2e 后端启动需先种子（webServer 命令里 `uv run python -m scripts.seed_skills &&` 前置，或 spec 里直接调 API 判断跳过）。

- [ ] **Step 3: README + 全量回归 + Commit**

`backend/README.md` 补「skill 市场（计划 4）」：种子命令（`uv run python -m scripts.seed_skills`，幂等、老用户补装）、市场 API 一览、组装物化机制（卸载即时生效）、skill 定价与 kind="skill" 流水、admin PATCH、model_weight 只存不路由（延后）。

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q && cd ../frontend && npx vitest run`
Expected: 全绿

```bash
git add backend/tests/test_skills_flow.py backend/README.md frontend/e2e/
git commit -m "test(skills): market flow integration, README"
```

---

## Self-Review 记录

**1. Spec 覆盖**：
- §4.1 skills/skill_files/user_skills 三表（含 SKILL.md 正文、工具列表、模型权重、积分价格、是否默认安装）→ Task 1 ✅；一次性导入脚本（frontmatter 已在 2b 生成，本期解析入库）→ Task 2 ✅；注册自动安装全部官方默认 skill → Task 2（+存量用户补装，吸取计划 3 I3 教训）✅。
- §4.2 只读列表页+详情+安装/卸载、无自定义上传、后台加 skill=插库 → Task 3/7 ✅。
- §4.3 步骤 1「查用户已安装 skill」→ Task 5 ✅；步骤 2「skills=[用户已安装 skill 虚拟目录]」→ Task 5 物化（实体目录，per-thread 沙箱内，语义等同）✅；步骤 2「model=按 skill 权重选 flash/pro」→ **显式偏差**：组装时无法预知命中 skill，字段只存不路由，记延后清单 ⚠️；步骤 5「skill 调用固定价」→ Task 6 ✅。
- §7.3 admin skill 上架/下架 + 审计 → Task 4（顺带定价调整，运营必需）✅。
- 兑换码/订阅/支付、KB、news 不在本计划（计划 5+）。

**2. 占位符扫描**：无 TBD/空壳。Task 6 Step 1 是显式实证步骤（deepagents 工具名/参数名），带完成判据（grep 证据写报告）与兜底（_READ_TOOLS/参数名按实证微调），非未完成项。Task 7 页面给结构+验收不给逐行 JSX（与计划 2b/3 同粒度），由 vitest+手工冒烟兜底。

**3. 类型一致性**：`Skill`/`UserSkill` 字段（Task 1）在 Task 2/3/4/5/6 一致；`upsert_skills/install_defaults`（Task 2）在 Task 3/5/6/8 测试一致消费；`load_installed_skills/write_skills`（Task 5）在 Task 8 一致；`extract_used_skills`（Task 6）签名一致；`kind="skill"` 全程统一；`build_agent(thread_id, checkpointer=None, skill_rows=None)` Task 5 定义 chat 消费一致。

**本计划显式延后（记入 ledger）**：
- model_weight 动态路由（flash/pro 按命中 skill 切换）——需运行中模型切换或子 agent 架构，归后续。
- skill 版本管理/更新推送（version 字段已存）。
- skill_files 附属文件的物化（表已建，19 个 skill 现无附属文件）。
- e2e 市场页若回退则补记。
