"""What logsift prints: one line per entry, and the summary."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from logsift.entries import LEVELS, Entry
from logsift.timefmt import format_utc


def format_entry(entry: Entry) -> str:
    """The printed form of one entry (time in UTC with milliseconds)."""
    return f"{format_utc(entry.time)} {entry.host} {entry.level} {entry.component}: {entry.message}"


def summarize(entries: Sequence[Entry]) -> str:
    """The text of ``logsift summary``: counts per level and per component."""
    lines = [f"entries: {len(entries)}"]
    if not entries:
        return "\n".join(lines) + "\n"
    times = [e.time for e in entries]
    lines.append(f"first: {format_utc(min(times))}")
    lines.append(f"last: {format_utc(max(times))}")
    by_level = Counter(e.level for e in entries)
    lines.append("levels:")
    lines.extend(f"  {level:<5} {by_level[level]}" for level in LEVELS)
    by_component = Counter(e.component for e in entries)
    lines.append("components:")
    for name in sorted(by_component):
        lines.append(f"  {name} {by_component[name]}")
    return "\n".join(lines) + "\n"
