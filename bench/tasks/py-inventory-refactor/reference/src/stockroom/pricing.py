"""Pricing an order: lines, discounts, shipping, and tax. No stock involved."""

from __future__ import annotations

from datetime import date
from typing import Any

from stockroom.catalog import Catalog
from stockroom.discounts import apply_discounts
from stockroom.errors import OrderError
from stockroom.money import percent_of
from stockroom.validation import validate_order


def quote_order(order: dict[str, Any], catalog: Catalog, today: date) -> dict[str, Any]:
    """The receipt of ``order`` without the ``reserved`` entry; nothing is reserved.

    Raises :class:`~stockroom.errors.OrderError` when the order is invalid.
    """
    problems = validate_order(order, catalog, today)
    if problems:
        raise OrderError(problems)
    country = catalog.countries[order["country"]]
    lines: list[dict[str, Any]] = []
    total_weight = 0
    for raw in order["lines"]:
        product = catalog.products[raw["sku"]]
        qty = raw["qty"]
        lines.append(
            {
                "sku": product.sku,
                "name": product.name,
                "qty": qty,
                "unit_cents": product.price_cents,
                "line_cents": product.price_cents * qty,
            }
        )
        total_weight += product.weight_g * qty
    subtotal = sum(line["line_cents"] for line in lines)
    discounts = apply_discounts(
        [(line["qty"], line["line_cents"]) for line in lines],
        order.get("coupon"),
        order.get("tier"),
    )
    discount_total = sum(cents for _name, cents in discounts)
    remaining = subtotal - discount_total
    kilograms = -(-total_weight // 1000)
    shipping = country.ship_base_cents + country.ship_per_kg_cents * kilograms
    if remaining >= country.free_over_cents:
        shipping = 0
    tax = percent_of(remaining, country.tax_pct)
    return {
        "order": order["id"],
        "customer": order["customer"],
        "country": country.code,
        "lines": lines,
        "subtotal_cents": subtotal,
        "discounts": [{"name": name, "cents": cents} for name, cents in discounts],
        "discount_cents": discount_total,
        "shipping_cents": shipping,
        "tax_cents": tax,
        "total_cents": remaining + shipping + tax,
    }
