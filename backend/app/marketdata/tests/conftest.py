"""marketdata 离线测试基座：用录制的真实 akshare 返回替换网络调用。

fixture 由 `scripts/spikes/record_marketdata_fixtures.py` 录制；
上游字段变动时重录，diff 即契约变更。
"""

from pathlib import Path

import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURE_DIR / f"{name}.csv", dtype={"指标": str, "选项": str})


@pytest.fixture
def fake_fetch_df(monkeypatch):
    """把 `fetch_df` 换成按 (endpoint, symbol) 查 fixture 的假实现。

    返回一个注册函数：`register(module, endpoint_substr, fixture_name)`。
    """
    registry: dict[tuple[str, str], str] = {}

    def _fetch_df(endpoint: str, func, *, retries: int = 1, **kwargs):
        symbol = str(kwargs.get("symbol", ""))
        code = "".join(c for c in symbol if c.isdigit())
        for (endpoint_key, symbol_key), fixture_name in registry.items():
            if endpoint_key in endpoint and (not symbol_key or symbol_key == code):
                return load_fixture(fixture_name)
        raise AssertionError(f"未注册的 fixture: endpoint={endpoint} symbol={symbol}")

    def register(module, endpoint_substr: str, fixture_name: str, symbol: str = ""):
        registry[(endpoint_substr, symbol)] = fixture_name
        monkeypatch.setattr(module, "fetch_df", _fetch_df)

    return register
