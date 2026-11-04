"""The plain-text invoice report and the one-line-per-invoice list."""

from __future__ import annotations

from collections.abc import Sequence

from invoicer.money import format_amount, format_rate
from invoicer.totals import InvoiceTotals

LABEL_WIDTH = 30
AMOUNT_WIDTH = 10


def row(label: str, amount: str) -> str:
    """One report row: the label (cut to its column) and the amount, right-aligned."""
    return f"  {label:<{LABEL_WIDTH}.{LABEL_WIDTH}}{amount:>{AMOUNT_WIDTH}}"


def render_invoice(invoice: InvoiceTotals) -> str:
    """One invoice: a header, a row per line, the subtotal, a row per VAT rate, the total."""
    lines = [f"{invoice.invoice}  {invoice.customer}".rstrip()]
    lines.extend(row(item.description, format_amount(item.amount)) for item in invoice.items)
    lines.append(row("subtotal", format_amount(invoice.subtotal)))
    lines.extend(
        row(f"vat {format_rate(rate)}%", format_amount(amount))
        for rate, amount in invoice.vat.items()
    )
    lines.append(row("total", format_amount(invoice.total)))
    return "\n".join(lines) + "\n"


def render(invoices: Sequence[InvoiceTotals]) -> str:
    """Every invoice, separated by blank lines (empty text when there are none)."""
    return "\n".join(render_invoice(invoice) for invoice in invoices)


def render_list(invoices: Sequence[InvoiceTotals]) -> str:
    """One line per invoice: the number, the customer, and the total."""
    return "".join(
        f"{invoice.invoice:<16}{invoice.customer:<30.30}{format_amount(invoice.total):>10}\n"
        for invoice in invoices
    )
