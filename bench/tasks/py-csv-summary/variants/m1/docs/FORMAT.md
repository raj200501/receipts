# csvsummary input and output format

The reporting jobs and the support dashboards parse the output of csvsummary, so this
format is fixed by the data platform team. Questions and change requests go to them.

## Input

- The input is UTF-8 text; a byte order mark at the start is ignored.
- The first line that is not blank is the header row. Column names must be unique
  and must not be empty.
- Fields are separated by commas, or by the character given with `--delimiter`
  (`--delimiter tab` for tab-separated files). A field may be quoted with double
  quotes; a double quote inside a quoted field is written twice.
- Blank lines between rows are skipped.
- A row with fewer fields than the header is padded with empty values, because the
  export tool leaves out empty fields at the end of a row. A row with more fields
  than the header is an error.

## csvsummary summary

The first lines give the number of data rows (the header row is not counted) and the
number of columns, followed by a blank line:

    rows: 6
    columns: 5

Then comes a header line and one line per column, in the order of the header row:

- `filled`: how many values are not empty (a value of only spaces counts as empty);
- `distinct`: how many different filled values there are, compared without
  surrounding spaces;
- `min`, `max`, `mean`: only when the column has filled values and every one of them
  is a plain decimal number (an optional sign, digits, and an optional decimal
  point followed by digits). `min` and `max` are printed as they are written in the
  file; `mean` has two decimal places. Other columns leave these fields blank.

## csvsummary top

One line per value, most common first; values with the same count are in the order
of the values themselves. Each line is the count right-aligned in six characters, two
spaces, and the value without surrounding spaces. An empty value is shown as
`(empty)`. At most 10 values are listed unless `--limit` gives another number.

## Line breaks inside values

A quoted field can contain line breaks. It is still one value of one row, so it
counts once in every count and statistic. In a listing every value is printed on a
single line: each line break inside the value is shown as the two characters `\n`.

## Listings for the ticket tracker

The support team pastes `csvsummary top` listings into the ticket tracker, which shows
the two characters `\n` literally. In a listing, each line break inside a value is
therefore printed as a single space, and `\n` never appears in a listing.

## Errors

A file that cannot be read stops the command before anything is printed. The message
goes to standard error, names the file and the line on which the offending row
starts, and the command exits with status 2.
