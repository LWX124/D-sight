import datetime as dt

from pydantic import BaseModel, Field


class ThreadCreateIn(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ThreadPatchIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ThreadOut(BaseModel):
    id: str
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime
