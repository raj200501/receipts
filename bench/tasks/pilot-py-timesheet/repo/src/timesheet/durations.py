"""Durations of entries in minutes, and the rounding rule from docs/POLICY.md."""

from __future__ import annotations

from datetime import time

from timesheet.entries import Entry

ROUND_TO = 15


def _clock(value: time) -> int:
    return value.hour * 60 + value.minute


def entry_minutes(entry: Entry) -> int:
    """Worked minutes of one entry, before rounding."""
    return _clock(entry.end) - _clock(entry.start)


def round_minutes(minutes: int, step: int = ROUND_TO) -> int:
    """Round to the nearest multiple of ``step``; a remainder of 7 minutes or less rounds down."""
    return (minutes + (step - 1) // 2) // step * step


def billable_minutes(entry: Entry) -> int:
    """Rounded minutes of one entry: the unit every total is built from."""
    return round_minutes(entry_minutes(entry))
