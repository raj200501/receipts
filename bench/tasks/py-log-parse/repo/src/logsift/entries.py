"""Log entries and their levels.

Every service of the shop logs through the same library, so its lines share one format
(see :mod:`logsift.parse`) and one set of levels, from least to most severe:
``DEBUG``, ``INFO``, ``WARN``, ``ERROR``, ``FATAL``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")


def severity(level: str) -> int:
    """The position of ``level`` in :data:`LEVELS` (0 for DEBUG, 4 for FATAL)."""
    return LEVELS.index(level)


@dataclass(frozen=True)
class Entry:
    """One parsed log line.

    Attributes:
        time: When it was logged, as an aware datetime in UTC.
        host: The host that wrote the line.
        level: One of :data:`LEVELS`.
        component: The part of the service that logged it (``checkout``, ``gateway``).
        message: The rest of the line.
        source: The file the line came from, as given on the command line.
        line: The 1-based line number in that file.
    """

    time: datetime
    host: str
    level: str
    component: str
    message: str
    source: str = "-"
    line: int = 0
