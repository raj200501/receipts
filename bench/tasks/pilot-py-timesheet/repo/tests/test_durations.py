import pytest
from timesheet.durations import billable_minutes, entry_minutes, round_minutes
from timesheet.entries import parse_entries

HEADER = "date,start,end,project,note\n"


def _entry(start: str, end: str):
    (entry,) = parse_entries(HEADER + f"2026-03-02,{start},{end},admin,\n")
    return entry


def test_entry_minutes_within_a_day() -> None:
    assert entry_minutes(_entry("09:00", "17:30")) == 510


@pytest.mark.parametrize(
    ("minutes", "rounded"),
    [(0, 0), (7, 0), (8, 15), (52, 45), (53, 60), (510, 510)],
)
def test_round_minutes_to_the_nearest_quarter_hour(minutes: int, rounded: int) -> None:
    assert round_minutes(minutes) == rounded


def test_billable_minutes_rounds_each_entry() -> None:
    assert billable_minutes(_entry("09:07", "10:00")) == 60
    assert billable_minutes(_entry("13:00", "13:07")) == 0
