"""Parse the dates and periods given on the command line.

A period is a single date (``2026-03-02``), a calendar month (``2026-03``), or an ISO
week (``2026-W10``). Every period stands for its first and its last date.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_MONTH = re.compile(r"(\d{4})-(\d{2})")
_WEEK = re.compile(r"(\d{4})-W(\d{2})")
DAYS_PER_WEEK = 7


class PeriodError(ValueError):
    """A date or period that cannot be parsed."""


def parse_date(text: str) -> date:
    """Parse a date written as ``YYYY-MM-DD`` (no other ISO forms)."""
    match = _DATE.fullmatch(text.strip())
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            pass
    raise PeriodError(f"not a date: {text!r} (expected YYYY-MM-DD)")


def weeks_in(year: int) -> int:
    """How many ISO weeks ``year`` has: 52, or 53 in a long year."""
    return date(year, 12, 28).isocalendar()[1]


def _month(year: int, number: int, text: str) -> tuple[date, date]:
    if not 1 <= number <= 12 or year < 1:
        raise PeriodError(f"not a month: {text!r} (months run from 01 to 12)")
    return date(year, number, 1), date(year, number, monthrange(year, number)[1])


def _week(year: int, number: int, text: str) -> tuple[date, date]:
    if year < 1 or not 1 <= number <= weeks_in(year):
        weeks = weeks_in(year) if year >= 1 else 52
        raise PeriodError(f"not an ISO week: {text!r} ({year} has weeks 01 to {weeks})")
    monday = date.fromisocalendar(year, number, 1)
    return monday, monday + timedelta(days=DAYS_PER_WEEK - 1)


def parse_period(text: str) -> tuple[date, date]:
    """The first and the last date of a period: a date, a month, or an ISO week."""
    value = text.strip()
    if _DATE.fullmatch(value):
        day = parse_date(value)
        return day, day
    month = _MONTH.fullmatch(value)
    if month:
        return _month(int(month.group(1)), int(month.group(2)), text)
    week = _WEEK.fullmatch(value)
    if week:
        return _week(int(week.group(1)), int(week.group(2)), text)
    raise PeriodError(f"not a date or period: {text!r} (expected YYYY-MM-DD, YYYY-MM, or YYYY-Www)")


def resolve(start: str, end: str | None = None) -> tuple[date, date]:
    """The dates a command covers: from the first date of START to the last date of END.

    Without END the command covers the period START alone.
    """
    first, last = parse_period(start)
    if end is not None:
        last = parse_period(end)[1]
    return first, last
