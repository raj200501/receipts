"""Date ranges: every date from a start date to an end date, both included."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, timedelta

ONE_DAY = timedelta(days=1)
DAYS_PER_WEEK = 7
WORKDAYS_PER_WEEK = 5


def date_range(start: date, end: date) -> Iterator[date]:
    """Every date from ``start`` to ``end``, both included, in order.

    The range is empty when ``end`` is before ``start``. Dates are produced one at a
    time, so a long range costs no memory.
    """
    current = start
    while current < end:
        yield current
        current += ONE_DAY


def weekdays(dates: Iterable[date]) -> Iterator[date]:
    """Only the Monday to Friday dates of ``dates``, in their order."""
    return (day for day in dates if day.weekday() < WORKDAYS_PER_WEEK)


def day_count(start: date, end: date) -> int:
    """How many dates the range from ``start`` to ``end`` has (0 when end is before start)."""
    return max(0, (end - start).days + 1)


def weekday_count(start: date, end: date) -> int:
    """How many Monday to Friday dates the range has, worked out without listing them."""
    total = day_count(start, end)
    full_weeks, rest = divmod(total, DAYS_PER_WEEK)
    count = full_weeks * WORKDAYS_PER_WEEK
    first = start.weekday()
    count += sum(
        1 for offset in range(rest) if (first + offset) % DAYS_PER_WEEK < WORKDAYS_PER_WEEK
    )
    return count
