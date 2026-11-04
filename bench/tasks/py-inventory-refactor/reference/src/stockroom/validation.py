"""Checking an order against the catalog, without pricing it or touching the stock."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from stockroom.catalog import Catalog
from stockroom.discounts import COUPONS, TIERS

MAX_LINES = 20
MAX_QTY = 100


def _header_problems(order: dict[str, Any], catalog: Catalog, today: date) -> list[str]:
    problems: list[str] = []
    order_id = order.get("id")
    if not isinstance(order_id, str) or not order_id.strip():
        problems.append("order id is missing")
    customer = order.get("customer")
    if not isinstance(customer, str) or not re.fullmatch(r"C-\d{3,6}", customer):
        problems.append(f"bad customer id {customer!r}")
    country_code = order.get("country")
    if not isinstance(country_code, str) or country_code not in catalog.countries:
        problems.append(f"cannot ship to country {country_code!r}")
    coupon = order.get("coupon")
    if coupon is not None:
        if coupon not in COUPONS:
            problems.append(f"unknown coupon {coupon!r}")
        elif today > COUPONS[coupon][3]:
            problems.append(f"coupon {coupon} expired on {COUPONS[coupon][3].isoformat()}")
    tier = order.get("tier")
    if tier is not None and tier not in TIERS:
        problems.append(f"unknown loyalty tier {tier!r}")
    return problems


def _line_problems(order: dict[str, Any], catalog: Catalog) -> list[str]:
    problems: list[str] = []
    raw_lines = order.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        return ["order has no lines"]
    if len(raw_lines) > MAX_LINES:
        problems.append(f"order has {len(raw_lines)} lines, the limit is {MAX_LINES}")
    first_seen: dict[str, int] = {}
    for number, raw in enumerate(raw_lines, start=1):
        sku = raw.get("sku") if isinstance(raw, dict) else None
        qty = raw.get("qty") if isinstance(raw, dict) else None
        product = catalog.products.get(sku) if isinstance(sku, str) else None
        if product is None:
            problems.append(f"line {number}: unknown sku {sku!r}")
        elif product.discontinued:
            problems.append(f"line {number}: {sku} is discontinued")
        elif sku in first_seen:
            problems.append(f"line {number}: {sku} already appears on line {first_seen[sku]}")
        else:
            first_seen[sku] = number
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
                problems.append(f"line {number}: quantity must be a whole number of at least 1")
            elif qty > MAX_QTY:
                problems.append(f"line {number}: quantity {qty} is above the limit of {MAX_QTY}")
    return problems


def validate_order(order: dict[str, Any], catalog: Catalog, today: date) -> list[str]:
    """Every problem with ``order``, in the order found; an empty list when it is valid.

    The order as a whole is checked first (id, customer, country, coupon, tier), then
    its lines. Stock is not part of this step.
    """
    return _header_problems(order, catalog, today) + _line_problems(order, catalog)
