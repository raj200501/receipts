from stockctl.filters import by_location, low_items, sort_items
from stockctl.items import parse_items

TEXT = """sku,name,qty,unit_price,location,reorder_at,updated
C-1,beta,5,1.00,dock,10,2026-01-01
A-1,Alpha,50,1.00,aisle-1,,2026-01-01
B-1,alpha two,20,1.00,dock,30,2026-01-01
D-1,Delta,1,1.00,aisle-1,2,2026-01-01
"""


def skus(items) -> list[str]:
    return [item.sku for item in items]


def test_by_location_keeps_one_location() -> None:
    assert skus(by_location(parse_items(TEXT), "dock")) == ["C-1", "B-1"]


def test_by_location_without_a_location_keeps_everything() -> None:
    assert len(by_location(parse_items(TEXT), None)) == 4


def test_by_location_is_exact() -> None:
    assert by_location(parse_items(TEXT), "Dock") == []


def test_low_items_most_short_first() -> None:
    assert skus(low_items(parse_items(TEXT))) == ["B-1", "C-1", "D-1"]


def test_sort_by_sku_is_the_default() -> None:
    assert skus(sort_items(parse_items(TEXT))) == ["A-1", "B-1", "C-1", "D-1"]


def test_sort_by_name_ignores_case() -> None:
    assert skus(sort_items(parse_items(TEXT), "name")) == ["A-1", "B-1", "C-1", "D-1"]


def test_sort_by_qty_largest_first() -> None:
    assert skus(sort_items(parse_items(TEXT), "qty")) == ["A-1", "B-1", "C-1", "D-1"]
    assert skus(sort_items(parse_items(TEXT), "qty")[::-1]) == ["D-1", "C-1", "B-1", "A-1"]
