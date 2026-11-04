# invoicer

Invoice totals for the monthly billing run. invoicer reads the CSV export of invoice
lines from the order system and prints every invoice with its lines, subtotal, VAT, and
total.

## Usage

    python3 -m invoicer totals examples/october.csv
    python3 -m invoicer totals examples/october.csv --invoice INV-2026-1042
    python3 -m invoicer list examples/october.csv

The export has a header row and one row per invoice line:

    invoice,customer,description,quantity,unit_price,vat_rate
    INV-2026-1042,Harbor Street Bakery,Espresso machine service,1,185.00,20

`quantity` and `unit_price` are decimal numbers (a credit line has a negative quantity),
and `vat_rate` is a percentage from 0 to 100. `NaN`, `inf`, and other values that are not
finite numbers are rejected. The lines with the same invoice number make up one invoice,
which takes its customer from its first line.

`invoicer totals` prints one block per invoice, in the order in which the invoices first
appear in the export, with a blank line between blocks:

    INV-2026-1042  Harbor Street Bakery
      Espresso machine service          185.00
      Descaling tablets (box of 10)      26.85
      subtotal                          211.85
      vat 7%                              1.88
      vat 20%                            37.00
      total                             250.73

Descriptions longer than 30 characters are cut in the report. `invoicer list` prints one
line per invoice with its number, customer, and total.

A row that cannot be read stops either command with a message that names its line, such
as `invoicer: line 4: invalid unit price 'seven'`, and the command exits with status 2.
So does a missing file or an unknown `--invoice` number.

The rules for rounding amounts and calculating VAT are finance's rounding policy in
[docs/ROUNDING.md](docs/ROUNDING.md): every amount is an exact decimal (never a binary
float), each line amount is rounded to the cent on its own with halves going to the even
cent (3 x 0.895 = 2.685 is 2.68), and the VAT of each rate is calculated once on the sum
of that rate's lines and rounded the same way (7% of 7.50 = 0.525 is 0.52).

## Library

    from pathlib import Path

    from invoicer import invoice_totals, read_items

    for invoice in invoice_totals(read_items(Path("examples/october.csv"))):
        print(invoice.invoice, invoice.subtotal, invoice.vat, invoice.total)

`read_items` returns `LineItem` objects (`amount` is the rounded line amount), and
`invoice_totals` returns one `InvoiceTotals` per invoice with its `subtotal`, `vat` (VAT
rate to VAT amount), and `total`. Every number is a `decimal.Decimal`. A row that cannot
be read raises `ItemError`, a `ValueError` whose message starts with `line N:`.

## Development

    python3 -m pytest -v

The package lives in `src/invoicer/` and uses only the standard library.
