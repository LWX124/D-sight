from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    return create_async_engine(get_settings().database_url)


def get_sessionmaker():
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db():
    async with get_sessionmaker()() as session:
        yield session
