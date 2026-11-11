"""The LRU cache."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable
from typing import Any

from tinycache.stats import Stats


class LRUCache:
    """A fixed-capacity mapping that evicts the least recently used entry."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be at least 1, got {capacity}")
        self._capacity = capacity
        self._data: OrderedDict[Hashable, Any] = OrderedDict()
        self._stats = Stats()

    @property
    def capacity(self) -> int:
        """The most entries the cache holds."""
        return self._capacity

    def get(self, key: Hashable, default: Any = None) -> Any:
        """The value for ``key`` (now most recently used), or ``default`` on a miss."""
        if key not in self._data:
            self._stats.misses += 1
            return default
        self._data.move_to_end(key)
        self._stats.hits += 1
        return self._data[key]

    def peek(self, key: Hashable, default: Any = None) -> Any:
        """The value for ``key`` without changing recency or statistics."""
        return self._data.get(key, default)

    def put(self, key: Hashable, value: Any) -> None:
        """Store ``value``; evict the least recently used entry when over capacity."""
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._capacity:
            self._data.popitem(last=False)
            self._stats.evictions += 1

    def delete(self, key: Hashable) -> bool:
        """Remove ``key``; True when it was present."""
        if key not in self._data:
            return False
        del self._data[key]
        return True

    def clear(self) -> None:
        """Remove every entry (the statistics are kept)."""
        self._data.clear()

    def keys(self) -> list[Hashable]:
        """The keys, least recently used first."""
        return list(self._data)

    def stats(self) -> dict[str, int]:
        """A snapshot of the counters."""
        return self._stats.as_dict()

    def reset_stats(self) -> None:
        """Set the counters back to zero."""
        self._stats.reset()

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)
