"""The advisory list: versions of a component that the security review flagged.

``data/advisories.json`` looks like::

    {"advisories": [{"id": "PW-2026-0007", "component": "gateway",
                     "affected": ">=1.3.0,<1.4.3", "summary": "header parsing overflow"}]}

``affected`` is a version range in the same form as a policy requirement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import tinyver

from pinwatch.errors import PinwatchError
from pinwatch.pins import read_json
from pinwatch.policy import parse_range


@dataclass(frozen=True)
class Advisory:
    """One advisory: which versions of which component are affected, and why."""

    id: str
    component: str
    affected: str
    summary: str


def load_advisories(path: str | Path) -> list[Advisory]:
    """The advisories in the file at ``path``, in file order.

    Raises:
        PinwatchError: the file is unreadable, has no ``advisories`` list, or an entry is
            missing a field or has a range that cannot be read.
    """
    document = read_json(path)
    entries = document.get("advisories") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise PinwatchError(f"{path}: expected an object with an 'advisories' list")
    advisories = []
    for index, entry in enumerate(entries):
        where = f"{path}: advisory {index + 1}"
        if not isinstance(entry, dict):
            raise PinwatchError(f"{where}: expected an object")
        fields = {}
        for field in ("id", "component", "affected", "summary"):
            value = entry.get(field)
            if not isinstance(value, str):
                raise PinwatchError(f"{where}: missing {field!r}")
            fields[field] = value
        parse_range(fields["affected"], f"{where} ({fields['id']})")
        advisories.append(Advisory(**fields))
    return advisories


def affected_pins(
    pins: Mapping[str, tinyver.Version], advisories: list[Advisory]
) -> list[tuple[Advisory, tinyver.Version]]:
    """The advisories that apply to a pin, with the pinned version, in advisory order."""
    found = []
    for advisory in advisories:
        pinned = pins.get(advisory.component)
        if pinned is not None and parse_range(advisory.affected, advisory.id).contains(pinned):
            found.append((advisory, pinned))
    return found
