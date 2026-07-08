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
