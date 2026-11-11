"""Clocks for the limiter: the real monotonic clock, and a manual one for replays and tests."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    """Anything whose ``now()`` returns seconds as a float that never goes back."""

    def now(self) -> float:
        """The current time in seconds."""
        ...


class MonotonicClock:
    """The system's monotonic clock, for the running gateway."""

    def now(self) -> float:
        """Seconds from ``time.monotonic``."""
        return time.monotonic()


class ManualClock:
    """A clock that moves only when told to: replays set it to each request's time."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        """The time the clock was last set to."""
        return self._now

    def set(self, value: float) -> None:
        """Move the clock to ``value``.

        Raises:
            ValueError: ``value`` is earlier than the current time.
        """
        if value < self._now:
            raise ValueError(f"the clock cannot go back from {self._now} to {value}")
        self._now = value

    def advance(self, seconds: float) -> None:
        """Move the clock forward by ``seconds`` (at least 0)."""
        if seconds < 0:
            raise ValueError(f"cannot advance the clock by {seconds} seconds")
        self._now += seconds
