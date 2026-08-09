import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class CredentialIn(BaseModel):
    # Do not put length constraints here: FastAPI's default validation payload
    # includes the rejected input and would echo an oversized Cookie. The
    # endpoint validates content and byte length with validate_cookies instead.
    cookies: str


class CredentialStatusOut(BaseModel):
    configured: bool
    status: Literal["active", "expired", "blocked"] | None
    weibo_uid: str | None
    nickname: str | None
    avatar: str | None
    last_verified_at: dt.datetime | None
    blocked_until: dt.datetime | None
    last_error: str | None
    can_manage: bool


class PreviewIn(BaseModel):
    profile_url: str = Field(min_length=1, max_length=1024)


class AccountOut(BaseModel):
    account_id: str
    uid: str
    name: str
    avatar: str | None
    description: str | None
    profile_url: str


class SubscriptionIn(BaseModel):
    account_id: str


class SubscriptionOut(BaseModel):
    id: str
    account_id: str
    uid: str
    name: str
    avatar: str | None
    description: str | None
    profile_url: str
    enabled: bool
    last_synced_at: dt.datetime | None
    last_sync_status: str
    last_sync_error: str | None


class SubscribeResult(BaseModel):
    subscription: SubscriptionOut
    initial_sync_status: str
    added: int


class MediaOut(BaseModel):
    type: Literal["image", "video"]
    url: str
    poster_url: str | None = None


class PostOut(BaseModel):
    id: str
    account_id: str
    account_name: str
    external_id: str
    content: str
    url: str
    media: list[MediaOut]
    published_at: dt.datetime
    captured_at: dt.datetime
