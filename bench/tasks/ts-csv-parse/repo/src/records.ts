/** Tables: CSV records as objects keyed by the names in the header row. */

import { CsvError } from "./errors.ts";
import type { CsvRow } from "./parse.ts";

/** One record: the value of every column, by column name. */
export type CsvRecord = Record<string, string>;

/** The column names of a file and its records, in file order. */
export interface Table {
  columns: string[];
  records: CsvRecord[];
}

/** The column names of a header row; every column needs a name, and no name may repeat. */
export function headerNames(header: CsvRow): string[] {
  const seen = new Set<string>();
  header.fields.forEach((name, index) => {
    if (name.trim() === "") {
      throw new CsvError(header.line, `column ${index + 1} has no name`);
    }
    if (seen.has(name)) {
      throw new CsvError(header.line, `column name ${JSON.stringify(name)} appears twice`);
    }
    seen.add(name);
  });
  return [...header.fields];
}

/** The table of ``rows``: the first row is the header, every other row is one record. */
export function toTable(rows: readonly CsvRow[]): Table {
  if (rows.length === 0) {
    return { columns: [], records: [] };
  }
  const [header, ...body] = rows;
  const columns = headerNames(header);
  const records = body.map((row) => {
    if (row.fields.length !== columns.length) {
      throw new CsvError(row.line, `expected ${columns.length} fields, got ${row.fields.length}`);
    }
    return Object.fromEntries(columns.map((name, index) => [name, row.fields[index]]));
  });
  return { columns, records };
}
