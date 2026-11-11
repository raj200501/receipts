"""The UTC offsets of the pay-batch hosts' clocks.

The pay-batch hosts log local time without a zone (``14/Oct/2026:10:05:00``), so logsift
needs to know each host's offset. They are kept in a JSON file::

    {"hosts": {"pay-batch-02": "+05:30"}}

The file is read the first time a legacy line needs it, so logs without legacy lines
never depend on it.
"""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

from logsift.timefmt import TimeFormatError, parse_offset

DEFAULT_PATH = "data/host-offsets.json"


class HostOffsetsError(ValueError):
    """The host offsets file is missing, damaged, or has no usable ``hosts`` table."""


def load_host_offsets(path: str | Path) -> dict[str, timezone]:
    """Read the offsets file and return a mapping from host name to its offset."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise HostOffsetsError(f"cannot read {path}: {exc.strerror or exc}") from None
    except ValueError as exc:
        raise HostOffsetsError(f"{path} is not valid JSON: {exc}") from None
    table = document.get("hosts") if isinstance(document, dict) else None
    if not isinstance(table, dict) or not table:
        raise HostOffsetsError(f"{path} has no 'hosts' table of host offsets")
    offsets: dict[str, timezone] = {}
    for host, text in table.items():
        try:
            offsets[str(host)] = parse_offset(str(text))
        except TimeFormatError as exc:
            raise HostOffsetsError(f"{path}: host {host!r}: {exc}") from None
    return offsets


class HostOffsets:
    """Host offsets loaded on first use from ``path``."""

    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._loaded: dict[str, timezone] | None = None

    def get(self, host: str) -> timezone | None:
        """The offset of ``host``, or ``None`` when the file does not list it."""
        if self._loaded is None:
            self._loaded = load_host_offsets(self.path)
        return self._loaded.get(host)
