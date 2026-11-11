"""Prepare invoices for the customer portal and sign the uploads.

The portal accepts one JSON document per invoice, signed with HMAC-SHA256 under the
billing team's portal key. The key is installed only on the billing server, at
``/etc/invoicer/portal.key``; the nightly upload job runs there.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from invoicer.money import format_amount, format_rate
from invoicer.totals import InvoiceTotals

PORTAL_KEY = Path("/etc/invoicer/portal.key")


def portal_document(invoice: InvoiceTotals) -> dict[str, object]:
    """The JSON document the customer portal accepts for one invoice (amounts as text)."""
    return {
        "invoice": invoice.invoice,
        "customer": invoice.customer,
        "lines": [
            {"description": item.description, "amount": format_amount(item.amount)}
            for item in invoice.items
        ],
        "subtotal": format_amount(invoice.subtotal),
        "vat": {format_rate(rate): format_amount(amount) for rate, amount in invoice.vat.items()},
        "total": format_amount(invoice.total),
    }


def sign(document: dict[str, object], key: bytes) -> str:
    """The hex HMAC-SHA256 of ``document`` as canonical JSON, under ``key``."""
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def load_portal_key(path: Path = PORTAL_KEY) -> bytes:
    """The portal key installed on the billing server."""
    return path.read_bytes().strip()
