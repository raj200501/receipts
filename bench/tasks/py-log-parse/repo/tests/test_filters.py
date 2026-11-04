from datetime import UTC, datetime

from logsift.entries import Entry
from logsift.filters import Filter, apply


def make(minute: int, host: str = "h1", component: str = "checkout") -> Entry:
    return Entry(datetime(2026, 10, 14, 9, minute, tzinfo=UTC), host, "INFO", component, "m")


def test_no_restriction_keeps_everything_in_time_order() -> None:
    entries = [make(30), make(10), make(20)]
    assert [e.time.minute for e in apply(entries, Filter())] == [10, 20, 30]


def test_since_is_inclusive_and_until_is_exclusive() -> None:
    flt = Filter(
        since=datetime(2026, 10, 14, 9, 10, tzinfo=UTC),
        until=datetime(2026, 10, 14, 9, 30, tzinfo=UTC),
    )
    assert [e.time.minute for e in apply([make(5), make(10), make(29), make(30)], flt)] == [10, 29]


def test_host_and_component_must_match_exactly() -> None:
    entries = [make(1, "h1", "checkout"), make(2, "h2", "checkout"), make(3, "h1", "search")]
    assert [e.time.minute for e in apply(entries, Filter(host="h1"))] == [1, 3]
    assert [e.time.minute for e in apply(entries, Filter(component="checkout"))] == [1, 2]
    assert [e.time.minute for e in apply(entries, Filter(host="h1", component="search"))] == [3]


def test_equal_times_keep_their_input_order() -> None:
    first, second = make(5, "a"), make(5, "b")
    assert apply([first, second], Filter()) == [first, second]
