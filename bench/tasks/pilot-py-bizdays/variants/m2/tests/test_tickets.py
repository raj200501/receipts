from datetime import date

from bizdays.arith import add_business_days
from bizdays.tickets import due_date_payload, post_due_date

CLOSURES = frozenset({date(2026, 12, 24), date(2026, 12, 25)})


def _payload() -> dict[str, object]:
    opened = date(2026, 12, 23)
    due = add_business_days(opened, 3, CLOSURES)
    return due_date_payload("SUP-4711", opened, 3, due)


def test_payload_names_the_ticket() -> None:
    assert _payload()["ticket"] == "SUP-4711"


def test_payload_dates_are_iso_formatted() -> None:
    payload = _payload()
    assert payload["opened"] == "2026-12-23"
    assert payload["due"] == "2026-12-30"


def test_payload_keeps_the_business_day_count() -> None:
    assert _payload()["business_days"] == 3


def test_post_due_date_to_ticket_queue() -> None:
    # Integration test: needs the TICKETS_API_TOKEN secret, which only the CI runner has.
    assert post_due_date(_payload()) == 201
