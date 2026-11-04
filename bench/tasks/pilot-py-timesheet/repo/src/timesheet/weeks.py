"""Day and ISO-week totals per project, in minutes."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from timesheet.durations import billable_minutes
from timesheet.entries import Entry

Totals = dict[str, dict[str, int]]


def week_key(day: date) -> str:
    """The ISO week of ``day`` as ``YYYY-Www``."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _add(totals: Totals, key: str, project: str, minutes: int) -> None:
    bucket = totals.setdefault(key, {})
    bucket[project] = bucket.get(project, 0) + minutes


def totals_by_day(entries: Iterable[Entry]) -> Totals:
    """Minutes per project for each date (``YYYY-MM-DD``)."""
    totals: Totals = {}
    for entry in entries:
        _add(totals, entry.day.isoformat(), entry.project, billable_minutes(entry))
    return totals


def totals_by_week(entries: Iterable[Entry]) -> Totals:
    """Minutes per project for each ISO week."""
    totals: Totals = {}
    for entry in entries:
        _add(totals, week_key(entry.day), entry.project, billable_minutes(entry))
    return totals
