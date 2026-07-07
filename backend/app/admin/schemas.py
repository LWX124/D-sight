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
