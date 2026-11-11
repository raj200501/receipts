# ledgerline

A small command-line tool that summarizes a personal expense ledger kept in a CSV file:
totals per category or month, the largest expenses, the categories in use, and a
currency converter that uses a table of exchange rates.

## Install

There is nothing to install. ledgerline needs Node 22.6 or newer and has no
dependencies. Run it from a checkout:

    node --experimental-strip-types bin/ledgerline.ts <command> [options]

## Usage

    ledgerline <command> [options]

`ledgerline` stands for `node --experimental-strip-types bin/ledgerline.ts` in the
examples below. Every example in this section is run by `npm run docs:check`, which
compares its output with what is shown here.

`ledgerline --help` prints the list of commands and `ledgerline --version` prints the
version; with no arguments ledgerline prints the help.

```
$ ledgerline --version
1.3.0
```

### summary

`ledgerline summary <file> [--by category|month] [--min AMOUNT]` prints the number of
expenses and their total, one row per group and a final Total row.

- `--by category` (the default) groups by category, `--by month` by calendar month. Rows
  are ordered by name.
- `--min AMOUNT` leaves out expenses below AMOUNT before grouping (refunds are below any
  positive minimum).

```
$ ledgerline summary examples/march.csv
Category   Count    Total
groceries      4   300.20
health         1    95.00
leisure        2    82.00
rent           1  1450.00
transport      1    32.50
utilities      1    67.30
Total         10  2027.00
$ ledgerline summary examples/q1.csv --by month
Month    Count    Total
2026-01      3  1585.10
2026-02      4  1669.60
2026-03      3  1574.40
Total       10  4829.10
$ ledgerline summary examples/march.csv --min 50
Category   Count    Total
groceries      3   259.05
health         1    95.00
leisure        1    58.00
rent           1  1450.00
utilities      1    67.30
Total          7  1929.35
```

### top

`ledgerline top <file> [-n N]` lists the largest expenses, biggest first, as rank, date,
category, amount, and description. `-n N` (or `--count N`) sets how many; the default is 5.
N must be a whole number of 1 or more. Expenses with the same amount keep their order in
the file.

```
$ ledgerline top examples/march.csv -n 3
 1. 2026-03-01  rent       1450.00  March rent
 2. 2026-03-12  health       95.00  Dentist, check-up
 3. 2026-03-17  groceries    92.75  Weekly shop
```

### categories

`ledgerline categories <file>` prints each category once with its number of expenses, in
alphabetical order.

```
$ ledgerline categories examples/april.csv
groceries (2)
leisure (1)
rent (1)
transport (1)
utilities (1)
```

### convert

`ledgerline convert <amount> <from> <to> [--rates FILE]` converts an amount between two
currencies using the rates file, `data/rates.json` unless `--rates` names another file
(see Exchange rates below). Currency codes are not case sensitive. The line shows the
amount, the converted amount, the rate between the two currencies, and the date of the
rates.

```
$ ledgerline convert 120 EUR GBP
120.00 EUR = 101.28 GBP (rate 0.8440, rates of 2026-10-30)
$ ledgerline convert 5000 czk jpy
5000.00 CZK = 33207.13 JPY (rate 6.6414, rates of 2026-10-30)
```

### Errors

A message that starts with `ledgerline:` goes to standard error and the exit status is 2
when the command or an option is unknown, an argument is missing or invalid, an input
file cannot be read, or a currency has no rate.

```
$ ledgerline summary examples/missing.csv
ledgerline: examples/missing.csv: cannot be read
$ ledgerline summary examples/march.csv --by year
ledgerline: --by must be category or month, not year
```

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
