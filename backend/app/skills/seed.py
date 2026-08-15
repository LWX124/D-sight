import hashlib
import logging
import re

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.workspace import SKILLS_DATA
from app.auth.models import User
from app.skills.models import Skill, UserSkill

logger = logging.getLogger(__name__)

PRO_SLUGS = {"investment-research", "deep-company-series"}
_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_skill_md(text: str, slug: str) -> dict:
    """解析 SKILL.md frontmatter，提取 name/description/category/tags。

    兼容纯键值对与 YAML 块；解析失败时回退到旧行为（只取 name/description）。
    """
    name, description, category, tags = slug, "", "research", []
    m = _FM.match(text)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        if isinstance(fm, dict):
            name = fm.get("name", slug) or slug
            description = fm.get("description", "") or ""
            qs = fm.get("quantSkills") or {}
            if isinstance(qs, dict):
                category = qs.get("category", "research") or "research"
                raw_tags = qs.get("tags", [])
                tags = raw_tags if isinstance(raw_tags, list) else []
    return {"name": name, "description": description, "body": text,
            "category": category, "tags": tags}


async def _deactivate_removed(db: AsyncSession, repo_slugs: set[str]) -> list[str]:
    """仓库里已删除的 skill 必须从货架上撤下。

    只刷新内容字段的策略有个盲区：目录被删后 upsert 再也不会碰到这一行，
    它带着最后一次的正文永远 is_active=True 挂在商店里——既装得上又跑不了。
    "内容不存在" 不是运营偏好而是事实，因此这里改 is_active；反向（重新加回
    目录）不自动上架，避免覆盖运维手动下架的决定。
    """
    stale = (await db.execute(
        select(Skill).where(Skill.is_active.is_(True), Skill.slug.notin_(repo_slugs))
    )).scalars().all() if repo_slugs else []
    for skill in stale:
        skill.is_active = False
    if stale:
        logger.info("skill 目录已删除，自动下架: %s", ", ".join(s.slug for s in stale))
    return [s.slug for s in stale]


async def upsert_skills(db: AsyncSession) -> int:
    from app.kb.providers import get_embedding_provider

    embedder = get_embedding_provider()
    root = SKILLS_DATA / "skills"
    count = 0
    to_embed: list[tuple] = []  # (skill_obj, source_text)
    repo_slugs: set[str] = set()

    for d in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        slug = d.name
        repo_slugs.add(slug)
        meta = parse_skill_md((d / "SKILL.md").read_text(encoding="utf-8"), slug)
        source_text = meta["description"] + " " + " ".join(meta["tags"])
        source_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]

        existing = (await db.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
        if existing is None:
            skill = Skill(
                slug=slug, name=meta["name"], description=meta["description"],
                body=meta["body"], category=meta["category"], tags=meta["tags"],
                model_weight="pro" if slug in PRO_SLUGS else "flash",
                embedding_source_hash=source_hash,
            )
            db.add(skill)
            await db.flush()
            to_embed.append((skill, source_text))
        else:  # 只刷新内容字段，运营字段（price/is_active/...）不动
            existing.name = meta["name"]
            existing.description = meta["description"]
            existing.body = meta["body"]
            existing.category = meta["category"]
            existing.tags = meta["tags"]
            if existing.embedding_source_hash != source_hash:
                existing.embedding_source_hash = source_hash
                to_embed.append((existing, source_text))
        count += 1

    await _deactivate_removed(db, repo_slugs)

    # 增量 embedding 回填；失败不阻断 skill 导入，降级全文匹配
    if to_embed:
        texts = [t for _, t in to_embed]
        try:
            vecs = await embedder.embed(texts)
            if len(vecs) != len(to_embed):
                raise RuntimeError(f"embedding 数量不匹配: {len(vecs)} != {len(to_embed)}")
            for (skill_obj, _), vec in zip(to_embed, vecs):
                skill_obj.embedding = vec
        except Exception as e:
            logger.warning("skill embedding 失败，降级全文匹配: %s", e)
            for skill_obj, _ in to_embed:
                skill_obj.embedding_source_hash = None  # 强制下次重试

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
