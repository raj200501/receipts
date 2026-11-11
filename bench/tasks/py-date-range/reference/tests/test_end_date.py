from datetime import date

import pytest
from dateseq.cli import main
from dateseq.ranges import date_range, day_count


def test_range_includes_the_end_date() -> None:
    dates = list(date_range(date(2026, 3, 2), date(2026, 3, 6)))
    assert dates == [date(2026, 3, day) for day in range(2, 7)]


def test_range_of_one_day_has_that_day() -> None:
    assert list(date_range(date(2026, 3, 5), date(2026, 3, 5))) == [date(2026, 3, 5)]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 3, 1), date(2026, 3, 31)),
        (date(2026, 2, 27), date(2026, 3, 2)),
        (date(2026, 12, 31), date(2027, 1, 1)),
    ],
)
def test_range_has_as_many_dates_as_day_count(start: date, end: date) -> None:
    assert len(list(date_range(start, end))) == day_count(start, end)


def test_list_prints_the_last_day_of_a_month(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "2026-03"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert (len(lines), lines[-1]) == (31, "2026-03-31")


def test_list_of_a_single_date(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "2026-03-05"]) == 0
    assert capsys.readouterr().out == "2026-03-05\n"


def test_list_of_an_iso_week_ends_on_sunday(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "2026-W10", "--format", "weekday"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "Sun 2026-03-08"
