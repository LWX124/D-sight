"""基金池 seed：读 seed_data/funds.yaml，按 fund_code upsert。"""
import asyncio
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.fund_arb.models import FundArbFund

SEED_PATH = Path(__file__).parent / "seed_data" / "funds.yaml"

FIELDS = [
    "fund_name", "category", "sina_symbol", "tracking_symbol", "tracking_type",
    "currency", "rate_type", "valuation_method", "nav_field",
    "pos_ratio_default", "approx", "enabled",
]


async def seed_funds(db: AsyncSession) -> int:
    data = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8"))
    existing = {
        f.fund_code: f
        for f in (await db.execute(select(FundArbFund))).scalars().all()
    }
    n = 0
    for entry in data["funds"]:
        code = str(entry["fund_code"])
        row = existing.get(code)
        if row is None:
            row = FundArbFund(fund_code=code)
            db.add(row)
        for k in FIELDS:
            if k in entry:
                setattr(row, k, entry[k])
        n += 1
    await db.commit()
    return n


if __name__ == "__main__":
    from app.core.db import get_sessionmaker

    async def _main():
        async with get_sessionmaker()() as db:
            n = await seed_funds(db)
        print(f"fund_arb seed 完成：{n} 只基金")

    asyncio.run(_main())
