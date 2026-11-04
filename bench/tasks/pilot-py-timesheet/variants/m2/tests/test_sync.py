from timesheet.entries import parse_entries
from timesheet.payroll import payload, push
from timesheet.weeks import totals_by_week

ROWS = """date,start,end,project,note
2026-03-02,09:00,12:00,billing,
2026-03-03,09:00,10:30,support,
"""


def test_payload_lists_minutes_per_project() -> None:
    document = payload("2026-W10", totals_by_week(parse_entries(ROWS)), "e-1042")
    assert document["minutes"] == {"billing": 180, "support": 90}


def test_payload_total_matches_the_projects() -> None:
    document = payload("2026-W10", totals_by_week(parse_entries(ROWS)), "e-1042")
    assert document["total_minutes"] == 270


def test_payload_for_a_week_without_entries_is_empty() -> None:
    document = payload("2026-W11", totals_by_week(parse_entries(ROWS)), "e-1042")
    assert document["minutes"] == {}
    assert document["total_minutes"] == 0


def test_push_week_to_payroll_service() -> None:
    # Needs the payroll daemon (/run/payroll/payroll.sock); it runs on staging hosts.
    document = payload("2026-W10", totals_by_week(parse_entries(ROWS)), "e-1042")
    assert push(document) == "ok"
