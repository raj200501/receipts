from pathlib import Path

import pytest
from stockroom.catalog import Catalog, CatalogError, load_catalog


def test_the_shipped_catalog_loads(catalog: Catalog) -> None:
    assert catalog.products["WGT-1"].price_cents == 450
    assert catalog.products["CBL-2"].backorder is True
    assert catalog.products["OLD-9"].discontinued is True
    assert catalog.countries["DE"].tax_pct == 19


def test_a_missing_catalog_is_reported(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="cannot read"):
        load_catalog(tmp_path / "none.json")


def test_a_catalog_without_countries_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text('{"products": {}}', encoding="utf-8")
    with pytest.raises(CatalogError, match="catalog layout"):
        load_catalog(path)
