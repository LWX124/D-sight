import httpx
import pytest
import respx

from poc.tools.runner import run_python
from poc.tools.stock import _sina_symbol
from poc.tools.web import BOCHA_ENDPOINT, fetch_page, web_search
from poc.tools import web as web_mod


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("920982", "bj920982"),  # 北交所 92 开头
        ("830799", "bj830799"),  # 北交所历史 8 开头
        ("430047", "bj430047"),  # 北交所历史 4 开头
        ("600519", "sh600519"),  # 沪市主板
        ("900901", "sh900901"),  # 沪市 B 股（9 开头但非 92）
        ("000001", "sz000001"),  # 深市主板
        ("300750", "sz300750"),  # 创业板
        ("200011", "sz200011"),  # 深市 B 股 2 开头
        ("sh600519", "sh600519"),  # 已带前缀原样返回
        ("BJ920982", "bj920982"),  # 大小写 + 前缀
    ],
)
def test_sina_symbol(code, expected):
    assert _sina_symbol(code) == expected


@respx.mock
def test_web_search_formats_results(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "test-key")
    respx.post(BOCHA_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "webPages": {
                        "value": [
                            {"name": "茅台财报", "url": "https://x.com/1", "summary": "净利润增长"}
                        ]
                    }
                }
            },
        )
    )
    out = web_search.invoke({"query": "贵州茅台 财报"})
    assert "茅台财报" in out and "https://x.com/1" in out and "净利润增长" in out


@respx.mock
def test_fetch_page_extracts_text():
    respx.get("https://example.com/a").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><article><p>贵州茅台2025年营收创新高，同比增长15%。</p></article></body></html>",
        )
    )
    out = fetch_page.invoke({"url": "https://example.com/a"})
    assert "贵州茅台" in out


def test_web_search_degrades_without_key(monkeypatch):
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    out = web_search.invoke({"query": "任意"})
    assert out.startswith("错误：搜索服务未配置")


def test_run_python_rejects_escape():
    out = run_python.invoke({"script": "../../etc/passwd"})
    assert out.startswith("错误")


def test_run_python_executes_workspace_script(tmp_path, monkeypatch):
    import poc.tools.runner as runner

    monkeypatch.setattr(runner, "WORKSPACE", tmp_path)
    (tmp_path / "hello.py").write_text("print('hi from tool')", encoding="utf-8")
    out = run_python.invoke({"script": "hello.py"})
    assert "exit=0" in out and "hi from tool" in out


def test_tool_guard_converts_exception_to_string():
    from poc.tools.safe import tool_guard

    @tool_guard
    def boom():
        raise ConnectionError("remote closed")

    out = boom()
    assert isinstance(out, str)
    assert out.startswith("错误：工具执行失败")
    assert "ConnectionError" in out


def test_fetch_page_returns_error_string_on_network_failure(monkeypatch):
    def raise_conn(*args, **kwargs):
        raise httpx.ConnectError("egress blocked")

    monkeypatch.setattr(web_mod.httpx, "get", raise_conn)
    out = fetch_page.invoke({"url": "https://blocked.example.com"})
    assert isinstance(out, str)
    assert out.startswith("错误：")


@respx.mock
def test_fetch_page_returns_error_string_on_403():
    respx.get("https://example.com/forbidden").mock(
        return_value=httpx.Response(403, text="nope")
    )
    out = fetch_page.invoke({"url": "https://example.com/forbidden"})
    assert isinstance(out, str)
    assert out.startswith("错误：")


def test_web_search_returns_error_string_on_http_error(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "test-key")

    def raise_conn(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(web_mod.httpx, "post", raise_conn)
    out = web_search.invoke({"query": "x"})
    assert isinstance(out, str)
    assert out.startswith("错误：")
