"""Processing an order: validate it, price it, and reserve its stock.

An order is a dictionary (usually read from JSON)::

    {"id": "SO-1001", "customer": "C-204", "country": "DE", "coupon": "SPRING10",
     "tier": "gold", "lines": [{"sku": "WGT-1", "qty": 12}]}

``coupon`` and ``tier`` are optional. :func:`process_order` returns the receipt, and takes
the reserved units off the stock only when the whole order went through. The rules for
the discounts are in docs/DISCOUNTS.md.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from stockroom.catalog import Catalog
from stockroom.money import percent_of
from stockroom.stock import Stock

MAX_LINES = 20
MAX_QTY = 100

#: Coupon code -> (kind, value, minimum merchandise value in cents, last valid day).
COUPONS: dict[str, tuple[str, int, int, date]] = {
    "SPRING10": ("percent", 10, 5000, date(2026, 12, 31)),
    "WELCOME5": ("flat", 500, 2000, date(2027, 3, 31)),
}
TIERS: dict[str, int] = {"silver": 3, "gold": 5}


class OrderError(ValueError):
    """The order was rejected. ``problems`` lists every reason, in the order found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def process_order(
    order: dict[str, Any], catalog: Catalog, stock: Stock, today: date
) -> dict[str, Any]:
    """Validate, price, and reserve ``order``; return its receipt.

    Raises :class:`OrderError` when the order is invalid or the stock cannot cover it.
    Nothing is taken off ``stock`` unless the whole order succeeds.
    """
    problems: list[str] = []

    # --- the order as a whole -------------------------------------------------------
    order_id = order.get("id")
    if not isinstance(order_id, str) or not order_id.strip():
        problems.append("order id is missing")
    customer = order.get("customer")
    if not isinstance(customer, str) or not re.fullmatch(r"C-\d{3,6}", customer):
        problems.append(f"bad customer id {customer!r}")
    country_code = order.get("country")
    country = catalog.countries.get(country_code) if isinstance(country_code, str) else None
    if country is None:
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

    # --- the lines --------------------------------------------------------------------
    raw_lines = order.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        problems.append("order has no lines")
        raw_lines = []
    elif len(raw_lines) > MAX_LINES:
        problems.append(f"order has {len(raw_lines)} lines, the limit is {MAX_LINES}")
    first_seen: dict[str, int] = {}
    wanted: list[tuple[int, str, int]] = []
    for number, raw in enumerate(raw_lines, start=1):
        sku = raw.get("sku") if isinstance(raw, dict) else None
        qty = raw.get("qty") if isinstance(raw, dict) else None
        product = catalog.products.get(sku) if isinstance(sku, str) else None
        if product is None:
            problems.append(f"line {number}: unknown sku {sku!r}")
            continue
        if product.discontinued:
            problems.append(f"line {number}: {sku} is discontinued")
            continue
        if sku in first_seen:
            problems.append(f"line {number}: {sku} already appears on line {first_seen[sku]}")
            continue
        first_seen[sku] = number
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            problems.append(f"line {number}: quantity must be a whole number of at least 1")
            continue
        if qty > MAX_QTY:
            problems.append(f"line {number}: quantity {qty} is above the limit of {MAX_QTY}")
            continue
        wanted.append((number, sku, qty))
    if problems:
        raise OrderError(problems)
    assert country is not None
    assert isinstance(order_id, str) and isinstance(customer, str)

    # --- stock: every line must be covered, or backorderable ---------------------------
    reservations: list[dict[str, Any]] = []
    for number, sku, qty in wanted:
        product = catalog.products[sku]
        on_shelf = stock.available(sku)
        if qty <= on_shelf:
            reservations.append({"sku": sku, "from_stock": qty, "backordered": 0})
        elif product.backorder:
            reservations.append({"sku": sku, "from_stock": on_shelf, "backordered": qty - on_shelf})
        else:
            problems.append(f"line {number}: only {on_shelf} of {sku} in stock")
    if problems:
        raise OrderError(problems)

    # --- price the lines ------------------------------------------------------------------
    lines: list[dict[str, Any]] = []
    subtotal = 0
    total_weight = 0
    for _number, sku, qty in wanted:
        product = catalog.products[sku]
        line_cents = product.price_cents * qty
        lines.append(
            {
                "sku": sku,
                "name": product.name,
                "qty": qty,
                "unit_cents": product.price_cents,
                "line_cents": line_cents,
            }
        )
        subtotal += line_cents
        total_weight += product.weight_g * qty

    # --- discounts: volume per line, then the coupon, then the loyalty tier ----------------
    # Each discount after the first is taken from what is left after the ones before it.
    discounts: list[dict[str, Any]] = []
    remaining = subtotal
    volume = 0
    for line in lines:
        if line["qty"] >= 25:
            volume += percent_of(line["line_cents"], 10)
        elif line["qty"] >= 10:
            volume += percent_of(line["line_cents"], 5)
    if volume:
        discounts.append({"name": "volume", "cents": volume})
        remaining -= volume
    if coupon is not None:
        kind, value, minimum, _last_day = COUPONS[coupon]
        coupon_cents = 0
        if remaining >= minimum:
            if kind == "percent":
                coupon_cents = percent_of(remaining, value)
            else:
                coupon_cents = min(value, remaining)
        if coupon_cents:
            discounts.append({"name": "coupon", "cents": coupon_cents})
            remaining -= coupon_cents
    if tier is not None:
        loyalty = percent_of(remaining, TIERS[tier])
        if loyalty:
            discounts.append({"name": "loyalty", "cents": loyalty})
            remaining -= loyalty
    discount_total = subtotal - remaining

    # --- shipping and tax ------------------------------------------------------------------
    kilograms = -(-total_weight // 1000)
    shipping = country.ship_base_cents + country.ship_per_kg_cents * kilograms
    if remaining >= country.free_over_cents:
        shipping = 0
    tax = percent_of(remaining, country.tax_pct)
    total = remaining + shipping + tax

    # --- take the units off the shelf, now that nothing can fail -----------------------------
    for item in reservations:
        stock.take(item["sku"], item["from_stock"])

    return {
        "order": order_id,
        "customer": customer,
        "country": country.code,
        "lines": lines,
        "subtotal_cents": subtotal,
        "discounts": discounts,
        "discount_cents": discount_total,
        "shipping_cents": shipping,
        "tax_cents": tax,
        "total_cents": total,
        "reserved": reservations,
    }
