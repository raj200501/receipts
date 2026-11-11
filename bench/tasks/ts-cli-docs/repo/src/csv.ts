import { DataError } from "./errors.ts";

/** One line of the ledger. Amounts are kept in cents to avoid float drift. */
export interface Expense {
  date: string;
  category: string;
  description: string;
  cents: number;
}

const HEADER = ["date", "category", "description", "amount"];
const AMOUNT = /^-?\d+(\.\d{1,2})?$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Split one CSV line into fields; double quotes wrap fields that contain commas. */
export function splitLine(line: string): string[] {
  const fields: string[] = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') {
        current += '"';
        i++;
      } else if (ch === '"') {
        quoted = false;
      } else {
        current += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      fields.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  fields.push(current);
  return fields;
}

/** Parse an amount such as "12.50" into cents. */
export function parseCents(text: string): number {
  if (!AMOUNT.test(text)) {
    throw new DataError(`not an amount: ${text}`);
  }
  return Math.round(Number(text) * 100);
}

/** Parse the text of a ledger file (header line date,category,description,amount). */
export function parseLedger(text: string, name = "ledger"): Expense[] {
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
  if (lines.length === 0 || splitLine(lines[0] ?? "").join(",") !== HEADER.join(",")) {
    throw new DataError(`${name}: the first line must be ${HEADER.join(",")}`);
  }
  return lines.slice(1).map((line, index) => {
    const fields = splitLine(line);
    const where = `${name}:${index + 2}`;
    if (fields.length !== HEADER.length) {
      throw new DataError(`${where}: expected ${HEADER.length} fields, found ${fields.length}`);
    }
    const [date, category, description, amount] = fields as [string, string, string, string];
    if (!DATE.test(date)) {
      throw new DataError(`${where}: bad date ${date}`);
    }
    try {
      return { date, category: category.trim(), description, cents: parseCents(amount) };
    } catch (error) {
      throw new DataError(`${where}: ${(error as Error).message}`);
    }
  });
}
