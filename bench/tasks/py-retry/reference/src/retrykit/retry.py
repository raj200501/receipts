"""The retry decorator."""

from __future__ import annotations

import functools
import random
import time
from collections.abc import Callable
from typing import Any

from retrykit.defaults import DEFAULT_DELAY, MAX_TRIES
from retrykit.policies import load_policy
from retrykit.schedule import backoff_delay, jittered

OnRetry = Callable[[int, BaseException, float], None]


def retry(
    *,
    max_attempts: int | None = None,
    delay: float | None = None,
    backoff: float | None = None,
    max_delay: float | None = None,
    jitter: float = 0.0,
    seed: int | None = None,
    policy: str | None = None,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    on_retry: OnRetry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Call the decorated function again when it raises one of ``exceptions``.

    The function runs at most ``max_attempts`` times (default ``MAX_TRIES``). After a failed
    attempt that is not the last, the wait is ``delay * backoff ** (attempt - 1)``, capped at
    ``max_delay``, then scaled by ``1 + u`` with ``u`` drawn from ``random.Random(seed)``
    uniformly in [-jitter, jitter] (one draw per retry, a fresh generator for every call).
    ``on_retry(attempt, exc, wait)`` is called with that wait before sleeping. The exception
    of the last attempt is raised unchanged.

    ``policy`` names an entry of ``data/policies.json`` that supplies ``max_attempts``,
    ``delay``, ``backoff``, and ``max_delay``; arguments given explicitly win.
    """
    settings = load_policy(policy) if policy is not None else {}
    attempts = max_attempts if max_attempts is not None else settings.get("max_attempts", MAX_TRIES)
    base = delay if delay is not None else settings.get("delay", DEFAULT_DELAY)
    factor = backoff if backoff is not None else settings.get("backoff", 1.0)
    cap = max_delay if max_delay is not None else settings.get("max_delay")
    if attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {attempts}")
    if base < 0:
        raise ValueError(f"delay must not be negative, got {base}")
    if factor < 1:
        raise ValueError(f"backoff must be at least 1, got {factor}")
    if cap is not None and cap < 0:
        raise ValueError(f"max_delay must not be negative, got {cap}")
    if not 0 <= jitter <= 1:
        raise ValueError(f"jitter must be between 0 and 1, got {jitter}")

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            rng = random.Random(seed)
            attempt = 1
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt >= attempts:
                        raise
                    wait = jittered(backoff_delay(base, attempt, factor, cap), jitter, rng)
                    if on_retry is not None:
                        on_retry(attempt, exc, wait)
                    sleep(wait)
                    attempt += 1

        return wrapper

    return decorate
