import pytest
from stockroom.catalog import Catalog
from stockroom.orders import OrderError, reserve_stock
from stockroom.stock import Stock


def test_units_come_off_the_shelf(catalog: Catalog) -> None:
    stock = Stock({"WGT-1": 10})
    done = reserve_stock({"lines": [{"sku": "WGT-1", "qty": 4}]}, catalog, stock)
    assert done == [{"sku": "WGT-1", "from_stock": 4, "backordered": 0}]
    assert stock.available("WGT-1") == 6


def test_a_short_line_takes_nothing(catalog: Catalog) -> None:
    stock = Stock({"WGT-1": 10, "WGT-2": 1})
    order = {"lines": [{"sku": "WGT-1", "qty": 4}, {"sku": "WGT-2", "qty": 2}]}
    with pytest.raises(OrderError):
        reserve_stock(order, catalog, stock)
    assert stock.available("WGT-1") == 10
