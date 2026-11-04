"""Text output of the commands."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import tinyver


@dataclass(frozen=True)
class Row:
    """One component in the ``status`` table."""

    component: str
    pinned: tinyver.VersionTuple
    latest: tinyver.VersionTuple | None
    state: str


def show(version: tinyver.VersionTuple | None) -> str:
    """The text of ``version`` without a leading ``v``; ``-`` when there is none."""
    return "-" if version is None else tinyver.format_version(version)


def format_status(rows: Iterable[Row]) -> list[str]:
    """The lines of the status table: component, pinned, latest, state."""
    lines = []
    for row in rows:
        text = f"{row.component:<12}{show(row.pinned):<14}{show(row.latest):<14}{row.state}"
        lines.append(text.rstrip())
    return lines


def format_violation(component: str, pinned: tinyver.VersionTuple, requirement: str) -> str:
    """One line of the ``check`` output."""
    return f"{component}: {show(pinned)} is outside the policy {requirement}"
