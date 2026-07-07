from types import SimpleNamespace

import httpx
import pytest
import respx

from app.agent.tools.runner import make_run_python
from app.agent.tools.stock import _sina_symbol
from app.agent.tools.web import BOCHA_ENDPOINT, fetch_page, web_search


def _patch_bocha(monkeypatch, key: str):
    # web_search 从 settings 取 key（与 deepseek 一致，非 os.environ）；直接打桩 settings。
    monkeypatch.setattr(
        "app.agent.tools.web.get_settings",
        lambda: SimpleNamespace(bocha_api_key=key),
    )


@respx.mock
def test_web_search_formats_results(monkeypatch):
    _patch_bocha(monkeypatch, "test-key")
    respx.post(BOCHA_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"webPages": {"value": [
                {"name": "茅台财报", "url": "https://x.com/1", "summary": "净利润增长"}
            ]}}},
        )
    )
    out = web_search.invoke({"query": "贵州茅台 财报"})
    assert "茅台财报" in out and "净利润增长" in out


def test_web_search_degrades_without_key(monkeypatch):
    _patch_bocha(monkeypatch, "")
    assert web_search.invoke({"query": "任意"}).startswith("错误：搜索服务未配置")


@respx.mock
def test_fetch_page_gbk_no_mojibake():
    html = "<html><body><article><p>贵州茅台营收创新高，同比增长。</p></article></body></html>"
    respx.get("https://gbk.example.com/a").mock(
        return_value=httpx.Response(
            200,
            content=html.encode("gbk"),
            headers={"content-type": "text/html"},  # 无 charset，考验探测
        )
    )
    out = fetch_page.invoke({"url": "https://gbk.example.com/a"})
    assert "贵州茅台" in out  # PoC 输入#6：GBK 页面不得乱码


@respx.mock
def test_fetch_page_error_contract():
    respx.get("https://x.example.com/403").mock(return_value=httpx.Response(403))
    out = fetch_page.invoke({"url": "https://x.example.com/403"})
    assert out.startswith("错误：")


@pytest.mark.parametrize(
    ("code", "expected"),
    [("600519", "sh600519"), ("000001", "sz000001"), ("920982", "bj920982"),
     ("830799", "bj830799"), ("430047", "bj430047"), ("900901", "sh900901")],
)
def test_sina_symbol_mapping(code, expected):
    assert _sina_symbol(code) == expected


def test_run_python_scoped_to_workspace(tmp_path):
    (tmp_path / "hello.py").write_text("print('hi from ws')", encoding="utf-8")
    run_python = make_run_python(tmp_path)
    out = run_python.invoke({"script": "hello.py"})
    assert "exit=0" in out and "hi from ws" in out
    assert run_python.invoke({"script": "../../etc/passwd"}).startswith("错误")
