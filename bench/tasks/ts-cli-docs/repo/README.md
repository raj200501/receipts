# ledgerline

A small command-line tool that summarizes a personal expense ledger kept in a CSV file:
totals per category or month, the largest expenses, the categories in use, and a
currency converter that uses a table of exchange rates.

## Install

There is nothing to install. ledgerline needs Node 22.6 or newer and has no
dependencies. Run it from a checkout:

    node --experimental-strip-types bin/ledgerline.ts <command> [options]

## Usage

Run `ledgerline --help` for the list of commands.

## Ledger files

A ledger is a CSV file with the header `date,category,description,amount`. Dates are
`YYYY-MM-DD`, amounts are decimals with at most two places (negative amounts are
refunds), and a field that contains a comma is wrapped in double quotes. The
`examples/` directory has a few ledgers to try: `march.csv`, `april.csv`, and `q1.csv`.

## Exchange rates

`data/rates.json` holds the rates that `convert` uses: the base currency, the date of the
fixing, and the number of units of each currency per one unit of the base currency. The
treasury desk sends a new fixing every month; copy the numbers in by hand.

## Exit status

0 on success, 2 when the command line or an input file is wrong (a message starting with
`ledgerline:` goes to standard error).

## Tests

    npm test

The tests run with `node --test` and need no installation.
