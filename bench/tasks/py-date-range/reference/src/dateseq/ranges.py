"""Date ranges: every date from a start date to an end date, both included."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, timedelta

DAYS_PER_WEEK = 7
WORKDAYS_PER_WEEK = 5


def date_range(start: date, end: date, step: int = 1) -> Iterator[date]:
    """Every ``step``-th date from ``start`` to ``end``, both ends included, in order.

    ``step`` is the number of days from one date to the next (1 by default). The end
    date is included when a step lands on it, and the range never goes past it. The
    range is empty when ``end`` is before ``start``. Dates are produced one at a time,
    so a long range costs no memory.

    Raises:
        ValueError: ``step`` is not a whole number of at least 1 (raised at once, not
            when the first date is taken).
    """
    if isinstance(step, bool) or not isinstance(step, int) or step < 1:
        raise ValueError(f"the step must be a whole number of days of at least 1, got {step!r}")
    return _dates(start, end, timedelta(days=step))


def _dates(start: date, end: date, step: timedelta) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        try:
            current += step
        except OverflowError:  # past date.max: there is no later date to produce
            return


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
