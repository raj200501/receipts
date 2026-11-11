/** The csvtool command line: json, csv, and columns. */

import { readFileSync } from "node:fs";
import type { Dialect } from "./dialect.ts";
import { DialectError, delimiterOption } from "./dialect.ts";
import { CsvError } from "./errors.ts";
import { formatCsv } from "./format.ts";
import { readJsonLines, recordLine, tableRows } from "./jsonl.ts";
import { readRows } from "./parse.ts";
import type { Table } from "./records.ts";
import { toTable } from "./records.ts";

/** Where the command line writes its output. */
export interface Output {
  out: (text: string) => void;
  err: (text: string) => void;
}

export const USAGE = `usage: csvtool json FILE [--delimiter C]
       csvtool csv FILE [--delimiter C]
       csvtool columns FILE [--delimiter C]
`;

const COMMANDS: ReadonlySet<string> = new Set(["json", "csv", "columns"]);

/** What the command line was asked to do. */
export interface Invocation {
  command: string;
  file: string;
  dialect: Partial<Dialect>;
}

/** The command, the file, and the dialect, or null when the arguments are not usable. */
export function parseArguments(argv: readonly string[]): Invocation | null {
  const positional: string[] = [];
  const dialect: Partial<Dialect> = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--delimiter") {
      const value = argv[index + 1];
      if (value === undefined) {
        return null;
      }
      dialect.delimiter = delimiterOption(value);
      index += 1;
    } else if (arg.startsWith("--")) {
      return null;
    } else {
      positional.push(arg);
    }
  }
  if (positional.length !== 2 || !COMMANDS.has(positional[0])) {
    return null;
  }
  return { command: positional[0], file: positional[1], dialect };
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** What csvtool columns prints: one line per column with its position, then the counts. */
export function describeColumns(table: Table): string {
  const width = String(table.columns.length).length;
  const lines = table.columns.map((name, index) => `${String(index + 1).padStart(width)}  ${name}`);
  lines.push(`${plural(table.columns.length, "column")}, ${plural(table.records.length, "record")}`);
  return `${lines.join("\n")}\n`;
}

function run(invocation: Invocation, text: string): string {
  if (invocation.command === "csv") {
    return formatCsv(tableRows(readJsonLines(text)), invocation.dialect);
  }
  const table = toTable(readRows(text, invocation.dialect));
  if (invocation.command === "columns") {
    return describeColumns(table);
  }
  return table.records.map((record) => `${recordLine(record)}\n`).join("");
}

/** Run the command line and return the exit status. */
export function main(argv: readonly string[], output: Output): number {
  const invocation = parseArguments(argv);
  if (invocation === null) {
    output.err(USAGE);
    return 2;
  }
  let text: string;
  try {
    text = readFileSync(invocation.file, "utf8");
  } catch {
    output.err(`csvtool: cannot read ${invocation.file}\n`);
    return 2;
  }
  try {
    output.out(run(invocation, text));
  } catch (error) {
    if (error instanceof CsvError || error instanceof DialectError) {
      output.err(`csvtool: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
  return 0;
}
