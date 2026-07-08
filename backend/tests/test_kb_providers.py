import pytest

from app.kb import providers


@pytest.mark.asyncio
async def test_fake_embedding_deterministic_and_unit():
    p = providers.FakeEmbedding(1024)
    a = await p.embed(["贵州茅台", "贵州茅台"])
    assert a[0] == a[1] and len(a[0]) == 1024
    import math
    assert abs(math.sqrt(sum(x * x for x in a[0])) - 1.0) < 1e-6
    b = await p.embed(["不同文本"])
    assert b[0] != a[0]


@pytest.mark.asyncio
async def test_fake_reranker_orders_by_overlap():
    r = providers.FakeReranker()
    out = await r.rerank("茅台财报", ["茅台财报很好", "无关内容", "茅台"], top_n=2)
    assert len(out) == 2 and out[0][0] == 0  # 重叠最多的排第一


def test_get_provider_failloud(monkeypatch):
    monkeypatch.setattr("app.kb.providers.get_settings",
                        lambda: type("S", (), {"embedding_backend": "nope"})())
    with pytest.raises(RuntimeError):
        providers.get_embedding_provider()
    with pytest.raises(RuntimeError):
        providers.get_reranker()
