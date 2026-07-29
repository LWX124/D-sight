import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


def test_stock_tools_route_akshare_through_serial_gate(monkeypatch):
    """生产 call_akshare 在多线程并发下必须串行化，不得让多个 ak.* 同时执行。

    回归 MiniRacer/V8 地址池并发初始化崩溃：agent 并行调用多个行情工具时，
    若 call_akshare 没有串行化，多个线程同时进入 AkShare → MiniRacer，
    触发 libmini_racer.dylib 的 FATAL 并杀死整个后端进程。
    """
    from app.core.akshare_runtime import call_akshare

    gate_state = threading.Lock()
    active = 0
    max_active = 0

    def fake_native(value: int) -> int:
        nonlocal active, max_active
        with gate_state:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.02)  # 制造重叠窗口：若未串行，max_active 会 >1
            return value * 2
        finally:
            with gate_state:
                active -= 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda v: call_akshare(fake_native, v), range(8)))

    assert results == [v * 2 for v in range(8)]
    assert max_active == 1, f"call_akshare 未串行化，max_active={max_active}（应为 1）"


def test_stock_tools_use_call_akshare_not_raw_akshare():
    """工具源码不得直接调用 ak.*，必须经 call_akshare。"""
    import inspect
    import re

    import app.agent.tools.stock as stock_mod

    src = inspect.getsource(stock_mod)
    raw_calls = re.findall(r"ak\.\w+\(", src)
    # call_akshare(ak.xxx, ...) 形式里的 ak.xxx 是函数引用（传参），不是裸调用，
    # 通过检查该 ak.xxx 是否出现在 "call_akshare(" 上下文中来区分。
    real_calls = [
        c for c in raw_calls
        if f"call_akshare({c.rstrip('(')}" not in src
    ]
    assert not real_calls, f"工具直接调用了 ak.* 而非经 call_akshare: {real_calls}"
