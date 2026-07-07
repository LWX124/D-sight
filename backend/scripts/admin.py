"""管理 CLI：uv run python -m scripts.admin set-admin a@b.com / grant a@b.com 500"""
import asyncio
import sys

from sqlalchemy import select

from app.auth.models import User
from app.core.db import get_sessionmaker
from app.credits import service


async def _main(argv):
    cmd = argv[1]
    email = argv[2]
    async with get_sessionmaker()() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            print(f"no such user: {email}")
            return
        if cmd == "set-admin":
            user.role = "admin"
            await s.commit()
            print(f"{email} is now admin")
        elif cmd == "grant":
            await service.ensure_account(s, user.id)
            await service.grant(s, user.id, int(argv[3]), kind="adjust", ref_type="cli")
            await s.commit()
            print(f"granted {argv[3]} to {email}")
        else:
            print(f"unknown cmd: {cmd}")


if __name__ == "__main__":
    asyncio.run(_main(sys.argv))
