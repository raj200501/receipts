from pathlib import Path

import pytest
from stockroom.stock import Stock, StockError, load_stock, save_stock


def test_take_reduces_the_shelf() -> None:
    stock = Stock({"A": 5})
    stock.take("A", 2)
    assert stock.available("A") == 3


def test_take_never_goes_below_zero() -> None:
    stock = Stock({"A": 1})
    stock.take("A", 4)
    assert stock.available("A") == 0


def test_unknown_skus_have_nothing_on_the_shelf() -> None:
    assert Stock().available("Z") == 0


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "stock.json"
    save_stock(Stock({"B": 2, "A": 1}), path)
    assert load_stock(path).on_hand == {"A": 1, "B": 2}


@pytest.mark.parametrize("content", ["[]", '{"A": -1}', '{"A": "3"}', "nope"])
def test_bad_stock_files_are_reported(tmp_path: Path, content: str) -> None:
    path = tmp_path / "stock.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StockError):
        load_stock(path)
