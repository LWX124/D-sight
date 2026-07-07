import functools


def tool_guard(fn):
    """工具最外层护栏：任何异常转为错误字符串返回，绝不向 agent 循环抛异常。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return f"错误：工具执行失败（{type(exc).__name__}: {exc}）。请换用其他工具或如实告知用户。"

    return wrapper
