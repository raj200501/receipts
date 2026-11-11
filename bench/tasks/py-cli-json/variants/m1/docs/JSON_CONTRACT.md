# JSON encodings for stock data

This is the encoding contract of the dock scanners' nightly sync job, which will read
the machine-readable output of stockctl. It is owned by the warehouse integrations team;
questions about it go to them.

## Objects

Item objects carry the keys `sku`, `name`, `qty`, `unit_price`, `location`,
`reorder_at`, and `updated`. The summary object carries `items`, `units`, `low`,
`value`, and `locations`.

## Field encodings

- Counts and quantities (`qty`, `reorder_at`, `short_by`, `items`, `units`, `low`) are
  JSON integers.
- Money (`unit_price`, `value`) is a JSON string with a dot and exactly two decimal
  digits, no thousands separators: `"0.12"`, `"1234.50"`. The sync job reads these
  strings as decimals; it never reads money from a JSON number, because binary floats
  lose cents.
- Dates (`updated`) are JSON strings in the form `YYYY-MM-DD`.
- A value that is not set (`reorder_at` without a reorder level) is JSON `null`.

## Scanner firmware profile

The sync file is read by both the nightly sync job and the handheld scanners, and the
scanners parse it with a reader that has no string-to-decimal step. For the scanners,
money (`unit_price`, `value`) in the sync file is a JSON number written with exactly two
decimal digits and no quotes: `0.12`, `1234.50`. The firmware rejects a file in which
a money field is a string.
