from __future__ import annotations

import time
from collections.abc import Callable

from ..extensions import cache


def cached_call(key: str, builder: Callable[[], dict], *, ok_ttl: int, fail_ttl: int = 45, wait: float = 35.0) -> dict:
    hit = cache.get(key)
    if hit is not None:
        return hit
    lock = f"lock:{key}"
    if cache.add(lock, 1, timeout=int(wait) + 10):
        try:
            value = builder()
            cache.set(key, value, timeout=ok_ttl if value.get("ok", True) else fail_ttl)
            return value
        finally:
            cache.delete(lock)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(0.25)
        hit = cache.get(key)
        if hit is not None:
            return hit
    return builder()
