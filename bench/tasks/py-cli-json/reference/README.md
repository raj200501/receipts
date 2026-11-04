# stockctl

A small command-line tool for the stock room. It reads the CSV export of the warehouse
system and prints stock lists, a low-stock report, and a summary. (Synthetic project
written for receipts-bench; the data and names are made up.)

## Usage

    python3 -m stockctl list examples/stock.csv
    python3 -m stockctl list examples/stock.csv --location aisle-3 --sort qty
    python3 -m stockctl low examples/stock.csv
    python3 -m stockctl summary examples/stock.csv

`list` prints every item, one per line, sorted by SKU unless `--sort` says `name` or
`qty`. `low` prints the items whose quantity is at or below their reorder level.
`summary` prints the number of items, the units in stock, how many items are low, the
stock value, and the units per location. `list` and `low` accept `--location` to
limit the output to one location.

## The CSV file

The file has a header row and one row per item:

    sku,name,qty,unit_price,location,reorder_at,updated
    A-100,Hex bolt M8,240,0.12,aisle-3,100,2026-02-27

`qty` is a whole number, `unit_price` is an amount with at most two decimals,
`reorder_at` may be empty (the item is never low), and `updated` is an ISO date.
A row that cannot be read stops the command with a message that names its line, and the
command exits with status 2. A file that cannot be opened exits with status 2 as well.

## JSON output

`list`, `low`, and `summary` accept `--json`, which prints JSON instead of text:

    python3 -m stockctl list examples/stock.csv --json
    python3 -m stockctl summary examples/stock.csv --json

`list` and `low` print an array of item objects (`low` adds `short_by`), `summary`
prints one object with `items`, `units`, `low`, `value`, and `locations`. The encodings
follow [docs/JSON_CONTRACT.md](docs/JSON_CONTRACT.md): counts are integers, money is a
string with two decimals, dates are `YYYY-MM-DD`, and a missing reorder level is `null`.
With `--json` an unreadable file stops the command with status 2 as before, and the
error goes to stderr as one JSON object, `{"error": "...", "line": N}` (`line` is `null`
when the problem is not in a row).

## Development

    python3 -m pytest -v

The package lives in `src/stockctl/` and uses only the standard library.
