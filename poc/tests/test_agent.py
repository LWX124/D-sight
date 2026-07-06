import os

from poc.agent import SYSTEM_PROMPT, build_agent


def test_build_agent_compiles(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dummy")
    agent = build_agent()
    assert hasattr(agent, "stream") and hasattr(agent, "invoke")


def test_system_prompt_has_guardrails():
    assert "工具" in SYSTEM_PROMPT  # 必须实际调用工具
    assert "来源" in SYSTEM_PROMPT  # 数字给来源
    assert "编造" in SYSTEM_PROMPT  # 禁止编造
