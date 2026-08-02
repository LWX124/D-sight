from pydantic import BaseModel, Field


class KbCreate(BaseModel):
    name: str


class KbOut(BaseModel):
    id: str
    name: str
    is_shared: bool
    doc_count: int


class ItemIn(BaseModel):
    source_type: str
    source_ref_id: str


class ItemsIn(BaseModel):
    # 批量上限 50：再多会让请求内的 describe 循环拖长，且前端一次也选不了那么多
    items: list[ItemIn] = Field(min_length=1, max_length=50)


class ItemsResult(BaseModel):
    added: int
    duplicate: int
    failed: list[dict]


class SourceIn(BaseModel):
    source_type: str
    source_ref_id: str
    display_name: str


class SourceOut(BaseModel):
    id: str
    source_type: str
    source_ref_id: str
    display_name: str
    status: str
    enabled: bool
    error: str | None
    last_synced_at: str | None


class DocumentOut(BaseModel):
    id: str
    title: str
    filename: str | None
    status: str
    chunk_count: int
    error: str | None
    source_type: str
    source_url: str | None
    published_at: str | None


class DocumentDetailOut(DocumentOut):
    text: str | None
