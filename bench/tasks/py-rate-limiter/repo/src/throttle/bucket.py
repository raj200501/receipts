"""A token bucket: at most ``capacity`` tokens, refilled continuously at ``rate`` per second."""

from __future__ import annotations

from throttle.clock import Clock

# Refills are computed with floats; a shortfall below this counts as no shortfall.
EPSILON = 1e-9


class TokenBucket:
    """One client's bucket. Each request takes one token; a request is allowed while
    the bucket has a whole token left.

    Args:
        capacity: The most tokens the bucket holds (the client's burst).
        rate: Tokens added per second.
        clock: Where the time comes from.
        tokens: Tokens at the start (default: a full bucket).
    """

    def __init__(
        self, capacity: float, rate: float, clock: Clock, tokens: float | None = None
    ) -> None:
        if capacity <= 0 or rate <= 0:
            raise ValueError(f"capacity and rate must be positive, got {capacity} and {rate}")
        self.capacity = capacity
        self.rate = rate
        self._clock = clock
        self._tokens = capacity if tokens is None else max(0.0, min(tokens, capacity))
        self._updated = clock.now()

    def _refill(self) -> None:
        now = self._clock.now()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._updated = now

    def tokens(self) -> float:
        """The tokens in the bucket now."""
        self._refill()
        return self._tokens

    def try_take(self) -> bool:
        """Take one token if there is one; True when it was taken."""
        self._refill()
        if self._tokens + EPSILON < 1:
            return False
        self._tokens = max(0.0, self._tokens - 1)
        return True

    def seconds_until_token(self) -> float:
        """Seconds until the bucket has a whole token (0.0 when it has one now)."""
        self._refill()
        missing = 1 - self._tokens
        return 0.0 if missing <= EPSILON else missing / self.rate
