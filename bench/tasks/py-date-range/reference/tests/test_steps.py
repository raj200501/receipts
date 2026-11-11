from datetime import date

import pytest
from dateseq.cli import main
from dateseq.periods import PeriodError, parse_step
from dateseq.ranges import date_range


def test_range_with_a_step_of_three_days() -> None:
    dates = list(date_range(date(2026, 3, 1), date(2026, 3, 10), step=3))
    assert dates == [date(2026, 3, 1), date(2026, 3, 4), date(2026, 3, 7), date(2026, 3, 10)]


def test_range_with_a_step_stops_before_passing_the_end() -> None:
    dates = list(date_range(date(2026, 3, 1), date(2026, 3, 12), step=5))
    assert dates == [date(2026, 3, 1), date(2026, 3, 6), date(2026, 3, 11)]


@pytest.mark.parametrize("step", [0, -1, -7])
def test_range_rejects_a_step_below_one_day(step: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        date_range(date(2026, 3, 1), date(2026, 3, 10), step=step)


@pytest.mark.parametrize(("text", "days"), [("1", 1), ("3", 3), ("1w", 7), ("2w", 14)])
def test_parse_step(text: str, days: int) -> None:
    assert parse_step(text) == days


@pytest.mark.parametrize("text", ["0", "0w", "-2", "1.5", "3x", "w", ""])
def test_parse_step_rejects_other_values(text: str) -> None:
    with pytest.raises(PeriodError, match="not a step"):
        parse_step(text)


def test_list_with_a_step_in_weeks(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "2026-01-05", "2026-03-01", "--step", "2w"]) == 0
    assert capsys.readouterr().out.split() == [
        "2026-01-05",
        "2026-01-19",
        "2026-02-02",
        "2026-02-16",
    ]


def test_list_rejects_a_step_of_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "2026-03", "--step", "0"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("dateseq: not a step: '0'")
