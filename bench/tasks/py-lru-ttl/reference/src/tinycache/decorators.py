"""The memoize decorator."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any

from tinycache.cache import LRUCache
from tinycache.keys import make_key

_MISSING = object()


def memoize(
    maxsize: int = 128,
    *,
    ttl: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Cache a function's results by its arguments in an LRU cache of ``maxsize`` entries.

    With ``ttl`` (seconds) a result is recomputed once it is that old, measured with ``clock``.

    The wrapper exposes the cache as ``.cache`` and ``.cache_clear()``.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        cache = LRUCache(maxsize, ttl=ttl, clock=clock)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = make_key(args, kwargs)
            value = cache.get(key, _MISSING)
            if value is _MISSING:
                value = func(*args, **kwargs)
                cache.put(key, value)
            return value

        wrapper.cache = cache  # type: ignore[attr-defined]
        wrapper.cache_clear = cache.clear  # type: ignore[attr-defined]
        return wrapper

    return decorate
