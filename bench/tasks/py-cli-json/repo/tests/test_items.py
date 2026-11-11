from datetime import date
from decimal import Decimal

import pytest
from stockctl.items import Item, ItemError, parse_items

HEADER = "sku,name,qty,unit_price,location,reorder_at,updated\n"


def one(row: str) -> Item:
    (item,) = parse_items(HEADER + row + "\n")
    return item


def test_parse_reads_every_field() -> None:
    item = one("A-100,Hex bolt M8,240,0.12,aisle-3,100,2026-02-27")
    assert item == Item(
        sku="A-100",
        name="Hex bolt M8",
        qty=240,
        unit_price=Decimal("0.12"),
        location="aisle-3",
        reorder_at=100,
        updated=date(2026, 2, 27),
    )


def test_empty_reorder_level_means_none() -> None:
    assert one("B-215,Cable tie,60,6.25,aisle-7,,2026-03-02").reorder_at is None


def test_prices_are_kept_with_two_decimals() -> None:
    assert str(one("B-210,Cable tie,35,4.5,aisle-7,40,2026-03-02").unit_price) == "4.50"


def test_blank_lines_are_skipped() -> None:
    items = parse_items(HEADER + "\nA-1,Bolt,1,1.00,dock,,2026-01-02\n\n")
    assert [item.sku for item in items] == ["A-1"]


def test_quoted_names_may_contain_commas() -> None:
    assert one('A-2,"Bolt, long",3,1.00,dock,,2026-01-02').name == "Bolt, long"


def test_header_only_file_has_no_items() -> None:
    assert parse_items(HEADER) == []


def test_empty_file_is_an_error() -> None:
    with pytest.raises(ItemError, match="line 1"):
        parse_items("")


def test_wrong_header_is_an_error() -> None:
    with pytest.raises(ItemError, match="expected the header"):
        parse_items("sku,name\nA-1,Bolt\n")


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        ("A-1,Bolt,ten,1.00,dock,,2026-01-02", "qty must be a whole number"),
        ("A-1,Bolt,-3,1.00,dock,,2026-01-02", "qty must not be negative"),
        ("A-1,Bolt,3,cheap,dock,,2026-01-02", "unit_price must be an amount"),
        ("A-1,Bolt,3,1.005,dock,,2026-01-02", "more than two decimals"),
        ("A-1,Bolt,3,1.00,dock,soon,2026-01-02", "reorder_at must be a whole number"),
        ("A-1,Bolt,3,1.00,dock,,02/01/2026", "updated must be an ISO date"),
        ("A-1,Bolt,3,1.00,dock,,", "updated must be an ISO date"),
        (",Bolt,3,1.00,dock,,2026-01-02", "sku is empty"),
        ("A-1,Bolt,3,1.00,,,2026-01-02", "location is empty"),
        ("A-1,Bolt,3", "expected 7 fields"),
    ],
)
def test_bad_rows_name_their_line(row: str, fragment: str) -> None:
    text = HEADER + "A-0,Washer,1,0.10,dock,,2026-01-01\n" + row + "\n"
    with pytest.raises(ItemError) as info:
        parse_items(text)
    assert info.value.line == 3
    assert fragment in str(info.value)
    assert str(info.value).startswith("line 3: ")


def test_duplicate_sku_names_both_lines() -> None:
    text = HEADER + "A-1,Bolt,1,1.00,dock,,2026-01-02\nA-1,Bolt,2,1.00,dock,,2026-01-02\n"
    with pytest.raises(ItemError, match=r"duplicate sku A-1 \(first on line 2\)"):
        parse_items(text)


def test_low_means_at_or_below_the_reorder_level() -> None:
    assert one("A-1,Bolt,10,1.00,dock,10,2026-01-02").is_low()
    assert not one("A-1,Bolt,11,1.00,dock,10,2026-01-02").is_low()
    assert not one("A-1,Bolt,0,1.00,dock,,2026-01-02").is_low()


def test_short_by_and_value() -> None:
    item = one("A-1,Bolt,4,2.50,dock,10,2026-01-02")
    assert item.short_by() == 6
    assert item.value() == Decimal("10.00")
