from pathlib import Path

import pytest
from csvsummary.cli import main
from csvsummary.reader import TableError, parse_table
from csvsummary.render import render_top

TICKETS = (
    "ticket,status,comment\n"
    '7001,open,"Screen flickers.\nWorse after the update."\n'
    "7002,closed,Password reset\n"
    '7003,open,"First visit.\n\nSecond visit."\n'
)


def test_quoted_line_breaks_stay_in_one_value() -> None:
    table = parse_table(TICKETS)
    assert [row.values[0] for row in table.rows] == ["7001", "7002", "7003"]
    assert table.rows[0].values[2] == "Screen flickers.\nWorse after the update."
    assert table.rows[2].values[2] == "First visit.\n\nSecond visit."


def test_rows_record_the_line_they_start_on() -> None:
    assert [row.line for row in parse_table(TICKETS).rows] == [2, 4, 5]


def test_too_many_fields_in_a_multiline_row_names_its_first_line() -> None:
    text = TICKETS + '7004,open,"Two\nlines",extra\n'
    with pytest.raises(TableError, match="line 8: expected at most 3 fields, got 4"):
        parse_table(text)


def test_listing_shows_line_breaks_as_backslash_n() -> None:
    assert render_top([("one\ntwo", 1)]) == "     1  one\\ntwo\n"


def test_summary_counts_multiline_rows_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "tickets.csv"
    path.write_text(TICKETS, encoding="utf-8")
    assert main(["summary", str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "rows: 3"
    assert lines[4] == "ticket        3         3  7001        7003        7002.00"


def test_top_of_other_columns_is_not_affected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "tickets.csv"
    path.write_text(TICKETS, encoding="utf-8")
    assert main(["top", str(path), "status"]) == 0
    assert capsys.readouterr().out == "     2  open\n     1  closed\n"
