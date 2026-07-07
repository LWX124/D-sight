"""脚本化假模型：支持 bind_tools 的最小 BaseChatModel，测试/E2E 用（FAKE_LLM=1）。

脚本语义：首轮返回一个工具调用（stock_quote 茅台）；之后任何一轮都返回固定文本答复。
"""

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeToolCallingModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeToolCallingModel":
        return self  # 工具签名忽略，脚本决定行为

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        has_tool_result = any(isinstance(m, ToolMessage) for m in messages)
        if has_tool_result:
            msg = AIMessage(content="假回复：茅台行情已查询，以上为工具返回的数据。")
        else:
            msg = AIMessage(
                content="",
                tool_calls=[
                    {"id": "fake-1", "name": "stock_quote", "args": {"symbol": "600519"}}
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])
