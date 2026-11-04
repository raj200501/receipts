"""Per-client token buckets: the decision the gateway makes for every request."""

from __future__ import annotations

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


class Limiter:
    """A token bucket per client, created full on the client's first request.

    Clients that have sent no request for ``idle_timeout_s`` seconds are forgotten, so
    a gateway that sees many short-lived clients does not keep a bucket for each of
    them forever.
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
        return Decision(False, int(bucket.seconds_until_token()))

    def tracked_clients(self) -> list[str]:
        """The clients the limiter keeps a bucket for, sorted (a gateway metric)."""
        return sorted(self._buckets)

    def _forget_idle(self, now: float) -> None:
        for client, seen in list(self._last_seen.items()):
            if now - seen >= self.idle_timeout_s:
                del self._buckets[client]
                del self._last_seen[client]
