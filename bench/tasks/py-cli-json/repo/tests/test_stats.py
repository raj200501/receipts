from decimal import Decimal

from stockctl.items import parse_items
from stockctl.stats import summarize

TEXT = """sku,name,qty,unit_price,location,reorder_at,updated
A-1,Bolt,10,0.25,aisle-1,5,2026-01-01
A-2,Nut,3,0.10,aisle-1,5,2026-01-01
B-1,Gloves,8,3.75,dock,,2026-01-01
"""


def test_summary_counts_items_units_and_low_items() -> None:
    summary = summarize(parse_items(TEXT))
    assert (summary.items, summary.units, summary.low) == (3, 21, 1)


def test_summary_value_is_a_two_decimal_amount() -> None:
    assert summarize(parse_items(TEXT)).value == Decimal("32.80")


def test_summary_units_per_location_are_sorted() -> None:
    assert list(summarize(parse_items(TEXT)).by_location.items()) == [("aisle-1", 13), ("dock", 8)]


def test_summary_of_nothing() -> None:
    summary = summarize([])
    assert (summary.items, summary.units, summary.value) == (0, 0, Decimal("0.00"))
