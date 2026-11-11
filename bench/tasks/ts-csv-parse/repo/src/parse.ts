/** Read CSV text into records of fields (the format is described in README.md). */

import type { Dialect } from "./dialect.ts";
import { resolveDialect } from "./dialect.ts";
import { CsvError } from "./errors.ts";

/** One record and the line of the input it starts on (1-based). */
export interface CsvRow {
  line: number;
  fields: string[];
}

const QUOTE = '"';
const BYTE_ORDER_MARK = "\uFEFF";

/**
 * Where the reader is in the current field: at its start, in an unquoted value, inside
 * the quotes of a quoted value, or after the closing quote of a quoted value.
 */
type FieldState = "start" | "plain" | "quoted" | "closed";

/** Read every record of ``text`` with the line it starts on; blank lines are skipped. */
export function readRows(text: string, options: Partial<Dialect> = {}): CsvRow[] {
  const { delimiter } = resolveDialect(options);
  const input = text.startsWith(BYTE_ORDER_MARK) ? text.slice(1) : text;
  const rows: CsvRow[] = [];
  let fields: string[] = [];
  let field = "";
  let state: FieldState = "start";
  let line = 1;
  let rowLine = 1;
  let quoteLine = 1;

  const endField = (): void => {
    fields.push(field);
    field = "";
    state = "start";
  };
  const endRecord = (): void => {
    const blank = fields.length === 0 && field === "" && state === "start";
    endField();
    if (!blank) {
      rows.push({ line: rowLine, fields });
    }
    fields = [];
  };

  for (let index = 0; index < input.length; index += 1) {
    const char = input[index];
    if (state === "quoted") {
      if (char === QUOTE) {
        state = "closed";
      } else {
        if (char === "\n") {
          line += 1;
        }
        field += char;
      }
      continue;
    }
    if (char === "\n" || (char === "\r" && input[index + 1] === "\n")) {
      if (char === "\r") {
        index += 1;
      }
      endRecord();
      line += 1;
      rowLine = line;
      continue;
    }
    if (char === delimiter) {
      endField();
      continue;
    }
    switch (state) {
      case "start":
        if (char === QUOTE) {
          state = "quoted";
          quoteLine = line;
        } else {
          field += char;
          state = "plain";
        }
        break;
      case "plain":
        if (char === QUOTE) {
          throw new CsvError(line, `unexpected quote in field ${fields.length + 1}`);
        }
        field += char;
        break;
      case "closed": {
        const what = char === QUOTE ? "quote" : "character";
        throw new CsvError(
          line,
          `unexpected ${what} after the closing quote of field ${fields.length + 1}`,
        );
      }
    }
  }
  if (state === "quoted") {
    throw new CsvError(quoteLine, `quoted field ${fields.length + 1} is not closed`);
  }
  if (fields.length > 0 || field !== "" || state !== "start") {
    endRecord();
  }
  return rows;
}

/** Parse CSV text into records of fields (readRows also gives each record's line). */
export function parseCsv(text: string, options: Partial<Dialect> = {}): string[][] {
  return readRows(text, options).map((row) => row.fields);
}
