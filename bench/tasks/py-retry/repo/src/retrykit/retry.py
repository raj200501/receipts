"""The retry decorator."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any

from retrykit.defaults import DEFAULT_DELAY, MAX_TRIES
from retrykit.schedule import fixed_delay

OnRetry = Callable[[int, BaseException, float], None]


def retry(
    *,
    delay: float = DEFAULT_DELAY,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    on_retry: OnRetry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Call the decorated function again when it raises one of ``exceptions``.

    The function runs at most ``MAX_TRIES`` times. After a failed attempt that is not the
    last, ``on_retry(attempt, exc, wait)`` is called and the decorator sleeps ``wait``
    seconds. The exception of the last attempt is raised unchanged.
    """
    if delay < 0:
        raise ValueError(f"delay must not be negative, got {delay}")

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 1
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt >= MAX_TRIES:
                        raise
                    wait = fixed_delay(delay, attempt)
                    if on_retry is not None:
                        on_retry(attempt, exc, wait)
                    sleep(wait)
                    attempt += 1

        return wrapper

    return decorate
