from datetime import UTC, datetime

from logsift.entries import Entry
from logsift.report import format_entry, summarize


def make(minute: int, level: str = "INFO", component: str = "checkout") -> Entry:
    return Entry(datetime(2026, 10, 14, 9, minute, tzinfo=UTC), "h1", level, component, "msg")


def test_format_entry_prints_utc_with_milliseconds() -> None:
    assert format_entry(make(5)) == "2026-10-14T09:05:00.000Z h1 INFO checkout: msg"


def test_summary_of_nothing_is_one_line() -> None:
    assert summarize([]) == "entries: 0\n"


def test_summary_counts_levels_and_components() -> None:
    text = summarize([make(5), make(9, "ERROR"), make(7, "INFO", "search")])
    assert text == (
        "entries: 3\n"
        "first: 2026-10-14T09:05:00.000Z\n"
        "last: 2026-10-14T09:09:00.000Z\n"
        "levels:\n"
        "  DEBUG 0\n"
        "  INFO  2\n"
        "  WARN  0\n"
        "  ERROR 1\n"
        "  FATAL 0\n"
        "components:\n"
        "  checkout 2\n"
        "  search 1\n"
    )
