from stockctl.items import parse_items
from stockctl.report import format_list, format_low, format_summary
from stockctl.stats import summarize

TEXT = """sku,name,qty,unit_price,location,reorder_at,updated
A-1,Bolt,10,0.25,aisle-1,5,2026-01-01
A-22,Hex nut,3,0.10,aisle-1,5,2026-01-01
"""


def test_list_is_a_table_with_a_header() -> None:
    assert format_list(parse_items(TEXT)).splitlines() == [
        "SKU   NAME     QTY  LOCATION",
        "A-1   Bolt      10  aisle-1",
        "A-22  Hex nut    3  aisle-1",
    ]


def test_list_of_nothing() -> None:
    assert format_list([]) == "(no items)\n"


def test_low_lines_say_how_far_below() -> None:
    assert format_low(parse_items(TEXT)[1:]) == (
        "A-22  Hex nut: 3 left, reorder at 5, short by 2\n"
    )


def test_low_of_nothing() -> None:
    assert format_low([]) == "nothing to reorder\n"


def test_summary_block() -> None:
    assert format_summary(summarize(parse_items(TEXT))).splitlines() == [
        "items: 2",
        "units: 13",
        "low: 1",
        "value: 2.80",
        "  aisle-1: 13",
    ]
