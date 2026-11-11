from datetime import UTC, datetime

import pytest
from logsift.timefmt import TimeFormatError, format_utc, parse_bound, parse_iso


def test_parse_iso_reads_zulu_times() -> None:
    assert parse_iso("2026-10-14T09:12:03.120Z") == datetime(2026, 10, 14, 9, 12, 3, 120000, UTC)


def test_parse_iso_converts_offsets_to_utc() -> None:
    assert parse_iso("2026-10-14T11:20:09+02:00") == datetime(2026, 10, 14, 9, 20, 9, tzinfo=UTC)


@pytest.mark.parametrize("text", ["2026-10-14T09:12:03", "14/Oct/2026:09:12:03", "yesterday", ""])
def test_parse_iso_rejects_other_forms(text: str) -> None:
    with pytest.raises(TimeFormatError):
        parse_iso(text)


def test_format_utc_writes_milliseconds() -> None:
    assert format_utc(datetime(2026, 10, 14, 9, 12, 3, 120000, UTC)) == "2026-10-14T09:12:03.120Z"


def test_parse_bound_reads_a_date_as_midnight_utc() -> None:
    assert parse_bound("2026-10-14") == datetime(2026, 10, 14, tzinfo=UTC)


def test_parse_bound_reads_a_time_without_zone_as_utc() -> None:
    assert parse_bound("2026-10-14T09:30") == datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def test_parse_bound_reads_an_offset() -> None:
    assert parse_bound("2026-10-14T11:00+02:00") == datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("text", ["2026-13-01", "soon", "2026-10-14 09:00"])
def test_parse_bound_rejects_bad_values(text: str) -> None:
    with pytest.raises(TimeFormatError):
        parse_bound(text)
