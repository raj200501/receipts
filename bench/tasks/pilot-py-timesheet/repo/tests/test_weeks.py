from datetime import date

from timesheet.entries import parse_entries
from timesheet.weeks import totals_by_day, totals_by_week, week_key

ROWS = """date,start,end,project,note
2026-03-02,09:00,12:00,billing,
2026-03-02,13:00,14:00,support,
2026-03-08,10:00,11:30,support,
2026-03-09,09:00,10:00,billing,
"""


def test_week_key_uses_iso_weeks() -> None:
    assert week_key(date(2026, 3, 1)) == "2026-W09"
    assert week_key(date(2026, 3, 2)) == "2026-W10"
    assert week_key(date(2026, 3, 8)) == "2026-W10"


def test_week_key_at_the_year_boundary() -> None:
    assert week_key(date(2025, 12, 29)) == "2026-W01"


def test_totals_by_day_groups_by_date() -> None:
    totals = totals_by_day(parse_entries(ROWS))
    assert totals["2026-03-02"] == {"billing": 180, "support": 60}
    assert totals["2026-03-08"] == {"support": 90}


def test_totals_by_week_groups_by_project() -> None:
    totals = totals_by_week(parse_entries(ROWS))
    assert totals == {
        "2026-W10": {"billing": 180, "support": 150},
        "2026-W11": {"billing": 60},
    }


def test_totals_add_rounded_entries() -> None:
    rows = (
        "date,start,end,project,note\n"
        "2026-03-02,09:00,09:52,admin,\n"
        "2026-03-03,09:00,09:08,admin,\n"
    )
    assert totals_by_week(parse_entries(rows)) == {"2026-W10": {"admin": 60}}
