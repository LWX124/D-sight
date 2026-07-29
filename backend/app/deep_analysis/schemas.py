"""深度分析 API Schemas。

命名规范：Request 后缀 = 入参，Response 后缀 = 出参。
"""
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DeepAnalysisCreateRequest(BaseModel):
    market: Literal["A", "HK", "US"]
    ticker: str = Field(min_length=1, max_length=32)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class DeepAnalysisCreateResponse(BaseModel):
    id: uuid.UUID
    status: str
    cache_hit: bool = False
    deduplicated: bool = False
    reserved_credits: int


class DeepAnalysisStatusResponse(BaseModel):
    id: uuid.UUID
    market: str
    ticker: str
    normalized_ticker: str
    status: str
    stage: str
    progress: int
    attempt_count: int
    conclusion_status: str | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DeepAnalysisListResponse(BaseModel):
    items: list[DeepAnalysisStatusResponse]
    next_cursor: str | None = None
