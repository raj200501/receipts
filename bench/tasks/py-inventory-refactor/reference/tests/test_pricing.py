from datetime import date

import pytest
from stockroom.catalog import Catalog
from stockroom.errors import OrderError
from stockroom.orders import process_order
from stockroom.pricing import quote_order
from stockroom.stock import Stock

TODAY = date(2026, 10, 14)
ORDER = {
    "id": "SO-7",
    "customer": "C-909",
    "country": "NL",
    "coupon": "SPRING10",
    "lines": [{"sku": "GAD-7", "qty": 12}, {"sku": "BLT-M6", "qty": 4}],
}


def test_a_quote_matches_the_receipt_of_the_processed_order(catalog: Catalog, stock: Stock) -> None:
    quote = quote_order(ORDER, catalog, TODAY)
    receipt = process_order(ORDER, catalog, stock, TODAY)
    assert {key: value for key, value in receipt.items() if key != "reserved"} == quote


def test_a_quote_has_no_reservation_entry(catalog: Catalog) -> None:
    assert "reserved" not in quote_order(ORDER, catalog, TODAY)


def test_a_quote_does_not_need_stock(catalog: Catalog) -> None:
    assert quote_order(ORDER, catalog, TODAY)["lines"][0]["qty"] == 12


def test_a_quote_rejects_invalid_orders(catalog: Catalog) -> None:
    with pytest.raises(OrderError):
        quote_order({**ORDER, "country": "XX"}, catalog, TODAY)
