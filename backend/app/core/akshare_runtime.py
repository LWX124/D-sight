"""串行执行 AkShare 调用，避免 MiniRacer/V8 并发初始化导致进程崩溃。"""
from collections.abc import Callable
from threading import Lock
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")

_akshare_lock = Lock()


def call_akshare(func: Callable[_P, _R], /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
    with _akshare_lock:
        return func(*args, **kwargs)
