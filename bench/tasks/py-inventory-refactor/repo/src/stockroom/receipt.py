"""The text form of a receipt (the dictionary that ``process_order`` returns)."""

from __future__ import annotations

from typing import Any

from stockroom.money import format_cents


def format_receipt(receipt: dict[str, Any]) -> str:
    """Render a receipt for the terminal: lines, discounts, shipping, tax, and total."""
    out = [f"Order {receipt['order']} for {receipt['customer']} ({receipt['country']})"]
    for line in receipt["lines"]:
        out.append(
            f"  {line['qty']:>3} x {line['sku']:<7} {line['name']:<22}"
            f" {format_cents(line['unit_cents']):>8} {format_cents(line['line_cents']):>9}"
        )
    out.append(f"subtotal{format_cents(receipt['subtotal_cents']):>40}")
    for discount in receipt["discounts"]:
        label = f"discount ({discount['name']})"
        out.append(f"{label:<16}{format_cents(-discount['cents']):>32}")
    out.append(f"shipping{format_cents(receipt['shipping_cents']):>40}")
    out.append(f"tax{format_cents(receipt['tax_cents']):>45}")
    out.append(f"total{format_cents(receipt['total_cents']):>43}")
    backordered = [r for r in receipt.get("reserved", []) if r["backordered"]]
    for item in backordered:
        out.append(f"backordered: {item['backordered']} x {item['sku']}")
    return "\n".join(out) + "\n"
