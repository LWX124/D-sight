import logging

_log = logging.getLogger(__name__)

RET_SESSION_EXPIRED = 200003
RET_FREQ_CONTROL = 200013


class MpError(Exception):
    """微信接口错误基类。"""


class SessionExpiredError(MpError):
    """会话失效（ret=200003）→ 凭证应标记 expired。"""


class TransientMpError(MpError):
    """临时错误（频控等非零码）→ 退避/跳过，不标 expired。"""


class FreqControlError(TransientMpError):
    """微信风控频率限制（ret=200013）→ 应触发全局冷却，期间不再发真实请求。

    继承 TransientMpError，既有 `except TransientMpError` 路径行为不变（凭证不标 expired）。
    """

    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after  # 建议等待秒数，0 表示未知


def check_base_resp(data: dict) -> dict:
    """校验微信响应；非 0 抛对应异常，成功原样返回 data。"""
    if "base_resp" not in data:
        raise TransientMpError(f"响应缺少 base_resp: {data}")
    ret = data["base_resp"].get("ret", 0)
    if ret == 0:
        return data
    err = data["base_resp"].get("err_msg", "")
    _log.warning("wechat mp non-zero ret: ret=%s err_msg=%s", ret, err)
    if ret == RET_SESSION_EXPIRED:
        raise SessionExpiredError(f"{ret}:{err}")
    if ret == RET_FREQ_CONTROL:
        raise FreqControlError(f"{ret}:{err}")
    raise TransientMpError(f"{ret}:{err}")
