"""Ready-made ``on_retry`` hooks."""

from __future__ import annotations

import logging
from collections.abc import Callable


def log_retry(
    logger: logging.Logger, level: int = logging.WARNING
) -> Callable[[int, BaseException, float], None]:
    """An ``on_retry`` hook that logs each failed attempt and the wait that follows."""

    def hook(attempt: int, exc: BaseException, delay: float) -> None:
        logger.log(
            level,
            "attempt %d failed (%s: %s); retrying in %.2f s",
            attempt,
            type(exc).__name__,
            exc,
            delay,
        )

    return hook
