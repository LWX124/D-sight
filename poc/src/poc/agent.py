import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

from poc.tools.runner import run_python
from poc.tools.stock import stock_financials, stock_quote
from poc.tools.web import fetch_page, web_search

WORKSPACE = Path(__file__).resolve().parents[2] / "workspace"

SYSTEM_PROMPT = """你是 D-sight 投研助手，服务中文投资者。

硬性规则：
1. 涉及行情、财务、新闻的事实，必须实际调用工具获取，禁止凭记忆编造数字。
2. 报告中的关键数字必须注明来源（工具名或 URL）。
3. 任务匹配某个 skill 描述时，先读入该 skill 的 SKILL.md 并严格按其步骤执行；\
skill 指定的交叉验证步骤（如 tools/financial_rigor.py）必须用 run_python 真实执行。
4. 简单概念问答（不涉及具体标的的实时数据）直接回答，不要启动重型研究流程。
5. 信息不足或数据不存在时（如未发布的财报），明确说明，不得编造。
"""


def build_agent(model_name: str | None = None):
    load_dotenv()
    model = ChatDeepSeek(
        model=model_name or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        api_key=os.environ["DEEPSEEK_API_KEY"],
        timeout=120,
        max_retries=3,
    )
    backend = FilesystemBackend(root_dir=str(WORKSPACE), virtual_mode=False)
    return create_deep_agent(
        model=model,
        tools=[web_search, fetch_page, stock_quote, stock_financials, run_python],
        backend=backend,
        skills=[str(WORKSPACE / "skills")],
        system_prompt=SYSTEM_PROMPT,
    )
