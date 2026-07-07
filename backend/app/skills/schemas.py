from pydantic import BaseModel


class SkillOut(BaseModel):
    slug: str
    name: str
    description: str
    category: str
    price: int
    model_weight: str
    is_default: bool
    installed: bool


class SkillDetail(SkillOut):
    body: str
