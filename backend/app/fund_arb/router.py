import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db, get_sessionmaker
from app.fund_arb.job import _now_sh, get_fetcher, is_market_open
from app.fund_arb.models import FundArbDaily
from app.fund_arb.schemas import DashboardOut, DashboardRow, HistoryOut, HistoryPoint
from app.fund_arb.snapshot import get_store, rebuild_snapshots

router = APIRouter(prefix="/api/fund-arb", tags=["fund_arb"])


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    category: str | None = None,
    user: User = Depends(get_current_user),
) -> DashboardOut:
    store = get_store()
    rows = [DashboardRow(**{
        k: getattr(s, k) for k in DashboardRow.model_fields
    }) for s in store.rows(category)]
    return DashboardOut(rows=rows, as_of=store.as_of, market_open=is_market_open(_now_sh()))


@router.get("/funds/{code}/history", response_model=HistoryOut)
async def history(
    code: str,
    days: int = Query(30, ge=1, le=180),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HistoryOut:
    since = dt.date.today() - dt.timedelta(days=days)
    rows = (await db.execute(
        select(FundArbDaily)
        .where(FundArbDaily.fund_code == code, FundArbDaily.date >= since)
        .order_by(FundArbDaily.date.asc())
    )).scalars().all()
    return HistoryOut(points=[
        HistoryPoint(date=r.date, price=r.price, nav=r.nav,
                     premium=r.premium, valuation_error=r.valuation_error)
        for r in rows
    ])


@router.post("/refresh")
async def refresh(user: User = Depends(get_current_user)) -> dict:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可手动刷新")
    n = await rebuild_snapshots(get_sessionmaker(), get_fetcher())
    return {"updated": n}
