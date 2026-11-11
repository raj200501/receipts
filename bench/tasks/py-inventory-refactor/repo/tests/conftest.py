from datetime import date
from pathlib import Path

import pytest
from stockroom.catalog import Catalog, load_catalog
from stockroom.stock import Stock, load_stock

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 14)


@pytest.fixture
def catalog() -> Catalog:
    return load_catalog(ROOT / "data" / "catalog.json")


@pytest.fixture
def stock() -> Stock:
    return load_stock(ROOT / "data" / "stock.json")
