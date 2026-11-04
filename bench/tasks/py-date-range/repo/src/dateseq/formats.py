"""Output formats for listed dates (``dateseq list --format NAME``)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def iso(day: date) -> str:
    """``2026-03-02``: the default."""
    return day.isoformat()


def compact(day: date) -> str:
    """``20260302``: for partition names such as ``dt=20260302``."""
    return f"{day.year:04d}{day.month:02d}{day.day:02d}"


def european(day: date) -> str:
    """``02.03.2026``: day, month, year."""
    return f"{day.day:02d}.{day.month:02d}.{day.year:04d}"


def with_weekday(day: date) -> str:
    """``Mon 2026-03-02``: the English weekday name, whatever the locale."""
    return f"{DAY_NAMES[day.weekday()]} {day.isoformat()}"


FORMATS: dict[str, Callable[[date], str]] = {
    "iso": iso,
    "compact": compact,
    "eu": european,
    "weekday": with_weekday,
}


def format_dates(dates: Iterable[date], name: str = "iso") -> Iterable[str]:
    """Each date in the format called ``name`` (KeyError for an unknown name)."""
    formatter = FORMATS[name]
    return (formatter(day) for day in dates)
