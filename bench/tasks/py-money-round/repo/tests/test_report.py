from invoicer.items import parse_items
from invoicer.report import render, render_list, row
from invoicer.totals import invoice_totals

ROWS = """invoice,customer,description,quantity,unit_price,vat_rate
INV-1,Harbor Street Bakery,Espresso machine service,1,185.00,20
INV-1,Harbor Street Bakery,Descaling tablets (box of 10),3,8.95,7
INV-2,Linden Dental Practice,Printer paper A4 (ream),12,4.35,20
"""

FIRST_BLOCK = """INV-1  Harbor Street Bakery
  Espresso machine service          185.00
  Descaling tablets (box of 10)      26.85
  subtotal                          211.85
  vat 7%                              1.88
  vat 20%                            37.00
  total                             250.73
"""


def test_row_aligns_the_label_and_the_amount() -> None:
    assert row("subtotal", "211.85") == "  subtotal                          211.85"


def test_row_cuts_long_labels() -> None:
    text = row("Annual maintenance contract for two espresso machines", "1.00")
    assert text == "  Annual maintenance contract fo      1.00"


def test_render_one_invoice() -> None:
    first, _ = invoice_totals(parse_items(ROWS))
    assert render([first]) == FIRST_BLOCK


def test_render_separates_invoices_with_a_blank_line() -> None:
    text = render(invoice_totals(parse_items(ROWS)))
    assert text.startswith(FIRST_BLOCK + "\nINV-2  Linden Dental Practice\n")
    assert text.endswith("  total                              62.64\n")


def test_render_prints_nothing_without_invoices() -> None:
    assert render([]) == ""


def test_render_list_prints_one_line_per_invoice() -> None:
    assert render_list(invoice_totals(parse_items(ROWS))).splitlines() == [
        "INV-1           Harbor Street Bakery              250.73",
        "INV-2           Linden Dental Practice             62.64",
    ]
