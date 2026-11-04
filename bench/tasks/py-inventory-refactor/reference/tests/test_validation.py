from datetime import date

from stockroom.catalog import Catalog
from stockroom.validation import validate_order

TODAY = date(2026, 10, 14)
GOOD = {
    "id": "SO-1",
    "customer": "C-204",
    "country": "DE",
    "lines": [{"sku": "WGT-1", "qty": 3}],
}


def test_a_valid_order_has_no_problems(catalog: Catalog) -> None:
    assert validate_order(GOOD, catalog, TODAY) == []


def test_problems_come_in_the_order_found(catalog: Catalog) -> None:
    bad = {**GOOD, "customer": "x", "tier": "platinum", "lines": [{"sku": "NOPE", "qty": 1}]}
    assert validate_order(bad, catalog, TODAY) == [
        "bad customer id 'x'",
        "unknown loyalty tier 'platinum'",
        "line 1: unknown sku 'NOPE'",
    ]


def test_quantity_limits(catalog: Catalog) -> None:
    lines = [{"sku": "WGT-1", "qty": 101}, {"sku": "WGT-2", "qty": True}]
    assert validate_order({**GOOD, "lines": lines}, catalog, TODAY) == [
        "line 1: quantity 101 is above the limit of 100",
        "line 2: quantity must be a whole number of at least 1",
    ]


def test_too_many_lines(catalog: Catalog) -> None:
    lines = [{"sku": "WGT-1", "qty": 1}] * 21
    problems = validate_order({**GOOD, "lines": lines}, catalog, TODAY)
    assert problems[0] == "order has 21 lines, the limit is 20"
    assert problems[1] == "line 2: WGT-1 already appears on line 1"


def test_an_expired_coupon(catalog: Catalog) -> None:
    problems = validate_order({**GOOD, "coupon": "WELCOME5"}, catalog, date(2027, 4, 1))
    assert problems == ["coupon WELCOME5 expired on 2027-03-31"]
