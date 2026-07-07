"""真实模型端到端冒烟：用有效 deepseek/bocha key 跑一个轻量真实问题。

默认跳过——CI 与常规 `pytest -q` 必须保持离线、免费。需显式开启：

    RUN_REAL_SMOKE=1 uv run pytest tests/test_real_smoke.py -s

会产生少量真实 API 费用。
"""

import os

import pytest

from app.agent.build import build_agent

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_SMOKE") != "1",
    reason="真实模型冒烟：需 RUN_REAL_SMOKE=1 且有效 deepseek/bocha key；默认跳过以保持离线免费。",
)


async def test_real_model_answers(tmp_path, monkeypatch):
    """FAKE_LLM=0 + 真实 key：问一个轻量实时问题，断言拿到非空文本回复。"""
    monkeypatch.setenv("FAKE_LLM", "0")
    from app.core import config

    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.deepseek_api_key, "缺 DEEPSEEK_API_KEY（应在 backend/.env）"

    import app.agent.workspace as ws_mod

    monkeypatch.setattr(ws_mod, "WORKSPACES_ROOT", tmp_path)
    agent = build_agent("real-smoke-1")
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "茅台现在多少钱"}]},
        config={"recursion_limit": 200},
    )
    final = result["messages"][-1]
    assert isinstance(final.content, str) and final.content.strip(), "真实模型未返回文本回复"
    print("\n[REAL SMOKE 回复]", final.content[:800])

    config.get_settings.cache_clear()
