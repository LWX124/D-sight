from pydantic import BaseModel


class NewsItemOut(BaseModel):
    id: str
    channel: str
    title: str | None
    content: str
    url: str | None
    published_at: str
