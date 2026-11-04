"""The LRU cache, with optional per-entry time-to-live."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

from tinycache.stats import Stats

_DEFAULT: Any = object()


def _check_ttl(ttl: float | None) -> None:
    if ttl is not None and not ttl > 0:
        raise ValueError(f"ttl must be a positive number of seconds, got {ttl!r}")


class LRUCache:
    """A fixed-capacity mapping that evicts the least recently used entry.

    With ``ttl`` (seconds) entries also expire: an entry is expired once its age, measured
    with ``clock``, is at least its lifetime (docs/EXPIRY.md).
    """

    def __init__(
        self,
        capacity: int,
        *,
        ttl: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be at least 1, got {capacity}")
        _check_ttl(ttl)
        self._capacity = capacity
        self._ttl = ttl
        self._clock = clock
        # key -> (value, stored_at, lifetime or None)
        self._data: OrderedDict[Hashable, tuple[Any, float, float | None]] = OrderedDict()
        self._stats = Stats()

    @property
    def capacity(self) -> int:
        """The most entries the cache holds."""
        return self._capacity

    @property
    def ttl(self) -> float | None:
        """The default lifetime in seconds (None: entries do not expire)."""
        return self._ttl

    @staticmethod
    def _expired(entry: tuple[Any, float, float | None], now: float) -> bool:
        _, stored_at, lifetime = entry
        return lifetime is not None and now - stored_at >= lifetime

    def _drop_if_expired(self, key: Hashable, now: float) -> bool:
        entry = self._data.get(key)
        if entry is None or not self._expired(entry, now):
            return False
        del self._data[key]
        self._stats.expirations += 1
        return True

    def _purge(self, now: float) -> int:
        dead = [key for key, entry in self._data.items() if self._expired(entry, now)]
        for key in dead:
            del self._data[key]
        self._stats.expirations += len(dead)
        return len(dead)

    def purge_expired(self) -> int:
        """Remove every expired entry and return how many there were."""
        return self._purge(self._clock())

    def get(self, key: Hashable, default: Any = None) -> Any:
        """The value for ``key`` (now most recently used), or ``default`` on a miss."""
        self._drop_if_expired(key, self._clock())
        if key not in self._data:
            self._stats.misses += 1
            return default
        self._data.move_to_end(key)
        self._stats.hits += 1
        return self._data[key][0]

    def peek(self, key: Hashable, default: Any = None) -> Any:
        """The value for ``key`` without changing recency or statistics."""
        entry = self._data.get(key)
        if entry is None or self._expired(entry, self._clock()):
            return default
        return entry[0]

    def put(self, key: Hashable, value: Any, ttl: float | None = _DEFAULT) -> None:
        """Store ``value``; ``ttl`` (seconds) overrides the cache's default lifetime.

        Expired entries are removed before the least recently used entry is evicted.
        """
        lifetime = self._ttl if ttl is _DEFAULT else ttl
        _check_ttl(lifetime)
        now = self._clock()
        self._data[key] = (value, now, lifetime)
        self._data.move_to_end(key)
        if len(self._data) > self._capacity:
            self._purge(now)
        while len(self._data) > self._capacity:
            self._data.popitem(last=False)
            self._stats.evictions += 1

    def delete(self, key: Hashable) -> bool:
        """Remove ``key``; True when a live entry was present."""
        if self._drop_if_expired(key, self._clock()) or key not in self._data:
            return False
        del self._data[key]
        return True

    def clear(self) -> None:
        """Remove every entry (the statistics are kept)."""
        self._data.clear()

    def keys(self) -> list[Hashable]:
        """The live keys, least recently used first."""
        self._purge(self._clock())
        return list(self._data)

    def stats(self) -> dict[str, int]:
        """A snapshot of the counters."""
        return self._stats.as_dict()

    def reset_stats(self) -> None:
        """Set the counters back to zero."""
        self._stats.reset()

    def __contains__(self, key: object) -> bool:
        self._drop_if_expired(key, self._clock())  # type: ignore[arg-type]
        return key in self._data

    def __len__(self) -> int:
        self._purge(self._clock())
        return len(self._data)
