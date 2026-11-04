from datetime import date
from typing import Any

import pytest
from stockroom.catalog import Catalog
from stockroom.orders import OrderError, process_order
from stockroom.stock import Stock

TODAY = date(2026, 10, 14)


def order(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "SO-1",
        "customer": "C-204",
        "country": "DE",
        "lines": [{"sku": "WGT-2", "qty": 2}],
    }
    base.update(changes)
    return base


def test_a_simple_order_is_priced(catalog: Catalog, stock: Stock) -> None:
    receipt = process_order(order(), catalog, stock, TODAY)
    assert receipt["subtotal_cents"] == 2580
    assert receipt["discounts"] == []
    assert receipt["shipping_cents"] == 490 + 120
    assert receipt["tax_cents"] == 490
    assert receipt["total_cents"] == 2580 + 610 + 490


def test_the_stock_is_reduced_after_success(catalog: Catalog, stock: Stock) -> None:
    process_order(order(), catalog, stock, TODAY)
    assert stock.available("WGT-2") == 83


def test_a_rejected_order_leaves_the_stock_alone(catalog: Catalog, stock: Stock) -> None:
    lines = [{"sku": "WGT-1", "qty": 5}, {"sku": "LMP-3", "qty": 10}]
    with pytest.raises(OrderError) as info:
        process_order(order(lines=lines), catalog, stock, TODAY)
    assert info.value.problems == ["line 2: only 9 of LMP-3 in stock"]
    assert stock.available("WGT-1") == 340


def test_backorderable_products_take_what_is_on_the_shelf(catalog: Catalog, stock: Stock) -> None:
    receipt = process_order(order(lines=[{"sku": "CBL-2", "qty": 8}]), catalog, stock, TODAY)
    assert receipt["reserved"] == [{"sku": "CBL-2", "from_stock": 5, "backordered": 3}]
    assert stock.available("CBL-2") == 0


def test_volume_discount_is_taken_per_line(catalog: Catalog, stock: Stock) -> None:
    lines = [{"sku": "WGT-1", "qty": 10}, {"sku": "WGT-2", "qty": 25}]
    receipt = process_order(order(lines=lines), catalog, stock, TODAY)
    assert receipt["discounts"] == [{"name": "volume", "cents": 225 + 3225}]


def test_coupon_and_tier_are_taken_from_what_is_left(catalog: Catalog, stock: Stock) -> None:
    lines = [{"sku": "GAD-7", "qty": 10}]
    receipt = process_order(
        order(lines=lines, coupon="SPRING10", tier="gold"), catalog, stock, TODAY
    )
    assert receipt["discounts"] == [
        {"name": "volume", "cents": 1248},
        {"name": "coupon", "cents": 2370},
        {"name": "loyalty", "cents": 1067},
    ]
    assert receipt["discount_cents"] == 1248 + 2370 + 1067


def test_a_coupon_below_its_minimum_gives_nothing(catalog: Catalog, stock: Stock) -> None:
    receipt = process_order(order(coupon="SPRING10"), catalog, stock, TODAY)
    assert receipt["discounts"] == []


def test_a_flat_coupon_is_taken_off(catalog: Catalog, stock: Stock) -> None:
    lines = [{"sku": "GAD-7", "qty": 1}]
    receipt = process_order(order(lines=lines, coupon="WELCOME5"), catalog, stock, TODAY)
    assert receipt["discounts"] == [{"name": "coupon", "cents": 500}]


def test_shipping_is_free_over_the_threshold(catalog: Catalog, stock: Stock) -> None:
    lines = [{"sku": "LMP-3", "qty": 3}]
    assert process_order(order(lines=lines), catalog, stock, TODAY)["shipping_cents"] == 0


def test_every_problem_is_listed_in_order(catalog: Catalog, stock: Stock) -> None:
    bad = order(
        id=" ",
        customer="204",
        country="XX",
        coupon="OLDCODE",
        tier="platinum",
        lines=[{"sku": "NOPE", "qty": 1}, {"sku": "WGT-1", "qty": 0}, {"sku": "OLD-9", "qty": 1}],
    )
    with pytest.raises(OrderError) as info:
        process_order(bad, catalog, stock, TODAY)
    assert info.value.problems == [
        "order id is missing",
        "bad customer id '204'",
        "cannot ship to country 'XX'",
        "unknown coupon 'OLDCODE'",
        "unknown loyalty tier 'platinum'",
        "line 1: unknown sku 'NOPE'",
        "line 2: quantity must be a whole number of at least 1",
        "line 3: OLD-9 is discontinued",
    ]


def test_an_expired_coupon_is_rejected(catalog: Catalog, stock: Stock) -> None:
    with pytest.raises(OrderError, match="coupon SPRING10 expired on 2026-12-31"):
        process_order(order(coupon="SPRING10"), catalog, stock, date(2027, 1, 2))


def test_a_repeated_sku_is_rejected(catalog: Catalog, stock: Stock) -> None:
    lines = [{"sku": "WGT-1", "qty": 1}, {"sku": "WGT-1", "qty": 2}]
    with pytest.raises(OrderError) as info:
        process_order(order(lines=lines), catalog, stock, TODAY)
    assert info.value.problems == ["line 2: WGT-1 already appears on line 1"]
