from pydantic import BaseModel


class KbCreate(BaseModel):
    name: str


class KbOut(BaseModel):
    id: str
    name: str
    is_shared: bool
    doc_count: int
