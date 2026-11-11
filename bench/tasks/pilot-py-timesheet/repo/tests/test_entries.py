from datetime import date, time
from pathlib import Path

import pytest
from timesheet.entries import EntryError, parse_entries, parse_time, read_entries

HEADER = "date,start,end,project,note\n"


def test_parse_time_reads_24_hour_times() -> None:
    assert parse_time("09:05") == time(9, 5)
    assert parse_time("23:59") == time(23, 59)


@pytest.mark.parametrize("text", ["9", "9:5", "24:00", "ab:cd", "09-30"])
def test_parse_time_rejects_other_formats(text: str) -> None:
    with pytest.raises(ValueError):
        parse_time(text)


def test_parse_entries_reads_rows() -> None:
    (entry,) = parse_entries(HEADER + "2026-03-02,09:00,12:30,billing,invoice run\n")
    assert entry.day == date(2026, 3, 2)
    assert (entry.start, entry.end) == (time(9, 0), time(12, 30))
    assert (entry.project, entry.note, entry.line) == ("billing", "invoice run", 2)


def test_note_is_optional() -> None:
    (entry,) = parse_entries("date,start,end,project\n2026-03-02,09:00,10:00,admin\n")
    assert entry.note == ""


def test_blank_lines_are_skipped_and_line_numbers_kept() -> None:
    text = HEADER + "\n2026-03-02,09:00,10:00,admin,\n\n2026-03-03,09:00,10:00,admin,\n"
    assert [entry.line for entry in parse_entries(text)] == [3, 5]


def test_header_is_required() -> None:
    with pytest.raises(EntryError, match="line 1"):
        parse_entries("2026-03-02,09:00,10:00,admin,\n")


def test_invalid_date_names_the_line() -> None:
    with pytest.raises(EntryError, match="line 2: invalid date"):
        parse_entries(HEADER + "2026-02-30,09:00,10:00,admin,\n")


def test_invalid_time_names_the_line() -> None:
    with pytest.raises(EntryError, match="line 3"):
        parse_entries(HEADER + "2026-03-02,09:00,10:00,admin,\n2026-03-03,9am,10:00,admin,\n")


def test_missing_project_names_the_line() -> None:
    with pytest.raises(EntryError, match="line 2: missing project"):
        parse_entries(HEADER + "2026-03-02,09:00,10:00,,\n")


def test_read_entries_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "entries.csv"
    path.write_text(HEADER + "2026-03-02,09:00,10:00,admin,\n", encoding="utf-8")
    assert len(read_entries(path)) == 1
