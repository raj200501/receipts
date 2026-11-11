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
