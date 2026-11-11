"""Hit, miss, and eviction counters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Stats:
    """Counters kept by a cache."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def lookups(self) -> int:
        """Hits plus misses."""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Share of lookups that were hits (0.0 before the first lookup)."""
        return self.hits / self.lookups if self.lookups else 0.0

    def as_dict(self) -> dict[str, int]:
        """The counters as a plain dict."""
        return {"hits": self.hits, "misses": self.misses, "evictions": self.evictions}

    def reset(self) -> None:
        """Set every counter back to zero."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
