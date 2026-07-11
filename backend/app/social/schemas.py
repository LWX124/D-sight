from pydantic import BaseModel


class SubscribeIn(BaseModel):
    fakeid: str
    name: str
    avatar: str | None = None


class AccountOut(BaseModel):
    id: str
    fakeid: str
    name: str
    avatar: str | None


class SubscriptionOut(BaseModel):
    id: str
    account_id: str
    fakeid: str
    name: str
    avatar: str | None
    enabled: bool


class ArticleOut(BaseModel):
    id: str
    account_id: str
    title: str
    digest: str | None
    cover_url: str | None
    url: str
    content: str | None
    published_at: str


class CredentialOut(BaseModel):
    id: str
    nickname: str
    avatar: str | None
    status: str
    expires_at: str
