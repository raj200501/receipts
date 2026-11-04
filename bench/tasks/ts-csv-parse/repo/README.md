# csvtool

A small CSV library and the `csvtool` command that the data team's import and export
scripts use. It turns CSV exports into JSON lines, turns JSON lines back into CSV, and
lists the columns of a file.

## Usage

    node --experimental-strip-types bin/csvtool.ts json examples/contacts.csv
    node --experimental-strip-types bin/csvtool.ts columns examples/contacts.csv
    node --experimental-strip-types bin/csvtool.ts csv records.jsonl
    npm run csvtool -- json --delimiter ";" finance-export.csv

- `csvtool json FILE` prints one JSON object per record, with the header names as keys
  in column order.
- `csvtool csv FILE` reads JSON lines (one object per line) and writes them as CSV. The
  columns are the keys in the order they first appear, and a record without one of them
  gets an empty value there. Strings are written as they are, numbers and booleans the
  way JSON writes them, and `null` as an empty value.
- `csvtool columns FILE` lists the header names with their position and counts the
  records.

Every command takes `--delimiter C` for files that do not use commas
(`--delimiter tab` for tab-separated files). Input that does not follow the format stops
the command with a message that names its line, and the command exits with status 2; so
does a file that cannot be read, or wrong arguments.

## The CSV format

csvtool reads and writes CSV the way RFC 4180 describes it:

- The first record is the header. Every other record has one field per column.
- Fields are separated by the delimiter, and records end with a line break (`\n` or
  `\r\n`). The line break after the last record is optional, blank lines are skipped,
  and a byte order mark at the start of the file is ignored.
- A field may be enclosed in double quotes. A quoted field may contain the delimiter
  and line breaks, and a double quote inside it is written as two double quotes:
  `"Ships to ""Dock 4"" only"` is the value `Ships to "Dock 4" only`.
- A field that is not quoted is read exactly as it is, spaces included. It cannot
  contain a double quote, and nothing but the delimiter or the end of the record may
  follow the closing quote of a quoted field.

When it writes CSV, csvtool puts a value in double quotes when it contains the
delimiter, a double quote, or a line break, or when it starts or ends with a space, and
it doubles every double quote inside a quoted value.

## Library

    import { parseCsv, readRows } from "./src/parse.ts";
    import { formatCsv } from "./src/format.ts";
    import { toTable } from "./src/records.ts";

    parseCsv('id,name\n7,"Lovelace, Ada"\n');
    // [["id", "name"], ["7", "Lovelace, Ada"]]
    readRows("id\n7\n");
    // [{ line: 1, fields: ["id"] }, { line: 2, fields: ["7"] }]
    toTable(readRows("id,name\n7,Ada\n"));
    // { columns: ["id", "name"], records: [{ id: "7", name: "Ada" }] }
    formatCsv([["id", "name"], ["7", "Lovelace, Ada"]]);
    // 'id,name\n7,"Lovelace, Ada"\n'

`readRows`, `parseCsv`, and `toTable` throw a `CsvError` (with the `line` the problem
was found on) for input that does not follow the format, and a `DialectError` for a
delimiter that cannot be used (the double quote or a line break).

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
