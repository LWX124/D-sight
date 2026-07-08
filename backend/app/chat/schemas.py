"""assistant-transport 协议 schema（对照官方示例 main.py 逐字移植）。

字段与 alias 与官方 assistant-ui LangGraph FastAPI 示例保持一致；本项目仅新增
``threadId`` 必填校验（在 router 侧处理，schema 保留 Optional 以兼容协议）。
"""

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class MessagePart(BaseModel):
    type: str
    text: str | None = None


class UserMessage(BaseModel):
    role: str
    parts: list[MessagePart]


class AddMessageCommand(BaseModel):
    type: Literal["add-message"]
    message: UserMessage


class AddToolResultCommand(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["add-tool-result"]
    tool_call_id: str = Field(alias="toolCallId")
    result: Any = None
    model_content: Any = Field(default=None, alias="modelContent")
    is_error: bool = Field(default=False, alias="isError")


Command = Annotated[
    Union[AddMessageCommand, AddToolResultCommand],
    Field(discriminator="type"),
]


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    system: str | None = None
    commands: list[Command]
    thread_id: str | None = Field(default=None, alias="threadId")
    mounted_kb_ids: list[str] | None = Field(default=None, alias="mountedKbIds")
    state: Any | None = None
