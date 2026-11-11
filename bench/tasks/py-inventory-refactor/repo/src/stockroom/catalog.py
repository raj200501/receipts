"""The product catalog and the shipping countries, loaded from ``data/catalog.json``."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class CatalogError(ValueError):
    """The catalog file is missing, unreadable, or not in the documented layout."""


@dataclass(frozen=True)
class Product:
    """One sellable product. Prices are in cents, weights in grams."""

    sku: str
    name: str
    price_cents: int
    weight_g: int
    discontinued: bool = False
    backorder: bool = False


@dataclass(frozen=True)
class Country:
    """Where the shop ships to, with its tax rate and shipping charges."""

    code: str
    tax_pct: int
    ship_base_cents: int
    ship_per_kg_cents: int
    free_over_cents: int


@dataclass(frozen=True)
class Catalog:
    """All products by SKU and all shipping countries by two-letter code."""

    products: dict[str, Product] = field(default_factory=dict)
    countries: dict[str, Country] = field(default_factory=dict)


def load_catalog(path: str | Path) -> Catalog:
    """Read the catalog file; raise :class:`CatalogError` when it cannot be used."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogError(f"cannot read {path}: {exc.strerror or exc}") from None
    except ValueError as exc:
        raise CatalogError(f"{path} is not valid JSON: {exc}") from None
    try:
        products = {
            sku: Product(
                sku=sku,
                name=item["name"],
                price_cents=int(item["price_cents"]),
                weight_g=int(item["weight_g"]),
                discontinued=bool(item.get("discontinued", False)),
                backorder=bool(item.get("backorder", False)),
            )
            for sku, item in document["products"].items()
        }
        countries = {
            code: Country(
                code=code,
                tax_pct=int(item["tax_pct"]),
                ship_base_cents=int(item["ship_base_cents"]),
                ship_per_kg_cents=int(item["ship_per_kg_cents"]),
                free_over_cents=int(item["free_over_cents"]),
            )
            for code, item in document["countries"].items()
        }
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise CatalogError(f"{path} does not have the catalog layout: {exc!r}") from None
    return Catalog(products=products, countries=countries)
