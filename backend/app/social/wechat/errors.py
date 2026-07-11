class MpError(Exception):
    """微信接口错误基类。"""


class SessionExpiredError(MpError):
    """会话失效（ret=200003）→ 凭证应标记 expired。"""


class TransientMpError(MpError):
    """临时错误（频控等非零码）→ 退避/跳过，不标 expired。"""


def check_base_resp(data: dict) -> dict:
    """校验微信响应；非 0 抛对应异常，成功原样返回 data。"""
    if "base_resp" not in data:
        raise TransientMpError(f"响应缺少 base_resp: {data}")
    ret = data["base_resp"].get("ret", 0)
    if ret == 0:
        return data
    err = data["base_resp"].get("err_msg", "")
    if ret == 200003:
        raise SessionExpiredError(f"{ret}:{err}")
    raise TransientMpError(f"{ret}:{err}")
