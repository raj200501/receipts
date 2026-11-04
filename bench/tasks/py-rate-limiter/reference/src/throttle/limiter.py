"""Per-client token buckets: the decision the gateway makes for every request."""

from __future__ import annotations

import math
from dataclasses import dataclass

from throttle.bucket import TokenBucket
from throttle.clock import Clock, MonotonicClock
from throttle.policy import Policy

IDLE_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class Decision:
    """The answer for one request: allowed, or rejected with a Retry-After in seconds."""

    allowed: bool
    retry_after_s: int = 0


def retry_after(seconds: float) -> int:
    """Whole seconds for a Retry-After: ``seconds`` rounded up, and at least 1.

    The refill arithmetic uses floats, so ``seconds`` is rounded to microseconds first;
    otherwise a wait of exactly 29 seconds computed as 29.000000000000004 would become 30.
    """
    return max(1, math.ceil(round(seconds, 6)))


class Limiter:
    """A token bucket per client, created full on the client's first request.

    A client that has sent no request for ``idle_timeout_s`` seconds is forgotten once
    its bucket has refilled completely, so a gateway that sees many short-lived clients
    does not keep a bucket for each of them forever. A full bucket holds exactly what a
    new one would, so forgetting it changes no decision; forgetting a bucket that is
    still refilling would hand the client a full burst too early.
    """

    def __init__(
        self, policy: Policy, clock: Clock | None = None, idle_timeout_s: float = IDLE_TIMEOUT_S
    ) -> None:
        self.policy = policy
        self.clock = clock if clock is not None else MonotonicClock()
        self.idle_timeout_s = idle_timeout_s
        self._buckets: dict[str, TokenBucket] = {}
        self._last_seen: dict[str, float] = {}

    def check(self, client: str) -> Decision:
        """Decide one request of ``client``: take a token from its bucket if it has one."""
        now = self.clock.now()
        self._forget_idle(now)
        bucket = self._buckets.get(client)
        if bucket is None:
            limit = self.policy.limit_for(client)
            bucket = TokenBucket(limit.burst, limit.per_second, self.clock)
            self._buckets[client] = bucket
        self._last_seen[client] = now
        if bucket.try_take():
            return Decision(True)
        return Decision(False, retry_after(bucket.seconds_until_token()))

    def tracked_clients(self) -> list[str]:
        """The clients the limiter keeps a bucket for, sorted (a gateway metric)."""
        return sorted(self._buckets)

    def _forget_idle(self, now: float) -> None:
        for client, seen in list(self._last_seen.items()):
            if now - seen < self.idle_timeout_s:
                continue
            bucket = self._buckets[client]
            if bucket.tokens() >= bucket.capacity:
                del self._buckets[client]
                del self._last_seen[client]
