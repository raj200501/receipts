from invoicer.items import parse_items
from invoicer.totals import invoice_totals
from invoicer.upload import load_portal_key, portal_document, sign

ROWS = """invoice,customer,description,quantity,unit_price,vat_rate
INV-1,Harbor Street Bakery,Espresso machine service,1,185.00,20
INV-1,Harbor Street Bakery,Descaling tablets,3,8.95,7
"""


def _document() -> dict[str, object]:
    (invoice,) = invoice_totals(parse_items(ROWS))
    return portal_document(invoice)


def test_document_lists_every_line() -> None:
    lines = _document()["lines"]
    assert lines == [
        {"description": "Espresso machine service", "amount": "185.00"},
        {"description": "Descaling tablets", "amount": "26.85"},
    ]


def test_document_amounts_are_text_with_two_decimals() -> None:
    document = _document()
    assert document["subtotal"] == "211.85"
    assert document["vat"] == {"7": "1.88", "20": "37.00"}
    assert document["total"] == "250.73"


def test_signature_depends_on_the_key() -> None:
    document = _document()
    assert sign(document, b"test-key-1") != sign(document, b"test-key-2")
    assert len(sign(document, b"test-key-1")) == 64


def test_sign_with_the_installed_portal_key() -> None:
    # Needs the portal key (/etc/invoicer/portal.key); it is installed only on the billing server.
    document = _document()
    assert len(sign(document, load_portal_key())) == 64
