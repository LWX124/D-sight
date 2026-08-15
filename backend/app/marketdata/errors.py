"""marketdata 类型化异常。

上层（diagnosis/evidence）按异常类型映射到 EvidenceStatus，
任何路径都不得以默认值代替失败。
"""


class MarketDataError(Exception):
    """marketdata 所有异常的基类。"""


class MarketNotSupported(MarketDataError):
    """请求的市场本层不提供数据（当前只支持 CN）。"""

    def __init__(self, market: str, capability: str = ""):
        self.market = market
        self.capability = capability
        suffix = f"（{capability}）" if capability else ""
        super().__init__(f"market={market} 不受支持{suffix}")


class SymbolNotFound(MarketDataError):
    """上游可达但查无此标的。"""

    def __init__(self, symbol: str, endpoint: str = ""):
        self.symbol = symbol
        self.endpoint = endpoint
        super().__init__(f"symbol={symbol} 在 {endpoint or '上游'} 无数据")


class UpstreamUnavailable(MarketDataError):
    """上游不可达：网络、代理、超时、限频、接口变更导致的调用失败。"""

    def __init__(self, endpoint: str, cause: BaseException | None = None):
        self.endpoint = endpoint
        self.cause = cause
        super().__init__(f"{endpoint} 调用失败: {type(cause).__name__ if cause else 'unknown'}: {cause}")


class DataIncomplete(MarketDataError):
    """上游返回了数据但缺少必需字段（对应 partial/missing）。"""

    def __init__(self, endpoint: str, missing: list[str]):
        self.endpoint = endpoint
        self.missing = missing
        super().__init__(f"{endpoint} 缺少字段: {', '.join(missing)}")
