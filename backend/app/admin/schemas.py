from pydantic import BaseModel


class CreditAdjust(BaseModel):
    user_id: str
    delta: int
    reason: str = ""


class PlanChange(BaseModel):
    plan: str  # free / subscribed


class SkillUpdate(BaseModel):
    is_active: bool | None = None
    price: int | None = None


class NewsSourceCreate(BaseModel):
    name: str
    type: str
    channel: str = "news"
    config: dict = {}
    interval_seconds: int = 300


class NewsSourceUpdate(BaseModel):
    enabled: bool | None = None
    config: dict | None = None
    interval_seconds: int | None = None
