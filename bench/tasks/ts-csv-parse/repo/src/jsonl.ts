/** JSON lines: one JSON object per line, as csvtool json writes them and csvtool csv reads them. */

import { CsvError } from "./errors.ts";
import type { CsvRecord, Table } from "./records.ts";

/** One record as a line of JSON, with its keys in column order. */
export function recordLine(record: CsvRecord): string {
  return JSON.stringify(record);
}

/** A JSON value as the text of a CSV field: numbers and booleans as JSON writes them. */
function fieldText(value: unknown, key: string, line: number): string {
  if (value === null) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  throw new CsvError(line, `${JSON.stringify(key)} is not a string, number, boolean, or null`);
}

/**
 * Read JSON lines into a table. The columns are the keys in the order they first appear;
 * a record without one of them gets an empty value there. Blank lines are skipped.
 */
export function readJsonLines(text: string): Table {
  const columns: string[] = [];
  const seen = new Set<string>();
  const objects: Array<{ line: number; object: Record<string, unknown> }> = [];
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = index + 1;
    if (raw.trim() === "") {
      return;
    }
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch {
      throw new CsvError(line, "not valid JSON");
    }
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      throw new CsvError(line, "expected a JSON object");
    }
    const object = value as Record<string, unknown>;
    for (const key of Object.keys(object)) {
      if (!seen.has(key)) {
        seen.add(key);
        columns.push(key);
      }
    }
    objects.push({ line, object });
  });
  const records = objects.map(({ line, object }) =>
    Object.fromEntries(
      columns.map((key) => [key, Object.hasOwn(object, key) ? fieldText(object[key], key, line) : ""]),
    ),
  );
  return { columns, records };
}

/** The rows csvtool csv writes for a table: the header row, then one row per record. */
export function tableRows(table: Table): string[][] {
  if (table.columns.length === 0) {
    return [];
  }
  return [[...table.columns], ...table.records.map((record) => table.columns.map((name) => record[name]))];
}
