import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.akshare_runtime import call_akshare


def test_call_akshare_serializes_concurrent_native_calls():
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def native_call(value: int) -> int:
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with state_lock:
            active -= 1
        return value * 2

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda value: call_akshare(native_call, value), range(4)))

    assert results == [0, 2, 4, 6]
    assert max_active == 1
