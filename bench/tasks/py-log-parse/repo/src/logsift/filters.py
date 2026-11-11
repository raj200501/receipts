"""Selecting entries: by time range, host, and component."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from logsift.entries import Entry


@dataclass(frozen=True)
class Filter:
    """What to keep. A field left at ``None`` does not restrict anything.

    ``since`` is inclusive and ``until`` is exclusive, so that two adjacent ranges never
    show an entry twice.
    """

    since: datetime | None = None
    until: datetime | None = None
    host: str | None = None
    component: str | None = None

    def matches(self, entry: Entry) -> bool:
        """True when ``entry`` passes every restriction."""
        if self.since is not None and entry.time < self.since:
            return False
        if self.until is not None and entry.time >= self.until:
            return False
        if self.host is not None and entry.host != self.host:
            return False
        return self.component is None or entry.component == self.component


def apply(entries: Iterable[Entry], flt: Filter) -> list[Entry]:
    """The entries that pass ``flt``, oldest first (stable for equal times)."""
    return sorted((e for e in entries if flt.matches(e)), key=lambda e: e.time)
