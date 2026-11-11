/** The accounting export: one CSV row per ledger entry, for the bookkeeper's import. */

import { decimalString } from "./format.ts";
import { parseMoney } from "./parse.ts";
import { MoneyError } from "./types.ts";
import type { Money } from "./types.ts";

export interface LedgerEntry {
  /** YYYY-MM-DD. */
  date: string;
  account: string;
  memo: string;
  amount: Money;
}

export const LEDGER_HEADER = "date,account,currency,amount,memo";

function quote(cell: string): string {
  return /[",\n]/.test(cell) ? `"${cell.replaceAll('"', '""')}"` : cell;
}

/** The export file for these entries: the header, then one row per entry, in order. */
export function exportLedger(entries: readonly LedgerEntry[]): string {
  const rows = entries.map((entry) =>
    [
      entry.date,
      entry.account,
      entry.amount.currency,
      decimalString(entry.amount),
      quote(entry.memo),
    ].join(","),
  );
  return `${[LEDGER_HEADER, ...rows].join("\n")}\n`;
}

/**
 * Read entries from a CSV with the header `date,account,memo,amount,currency`. Memos
 * cannot contain commas here. Blank rows are skipped.
 */
export function parseEntries(text: string): LedgerEntry[] {
  const rows = text.split(/\r?\n/).filter((row) => row.trim() !== "");
  if (rows[0]?.trim() !== "date,account,memo,amount,currency") {
    throw new MoneyError("expected the header date,account,memo,amount,currency");
  }
  return rows.slice(1).map((row, index) => {
    const line = index + 2;
    const cells = row.split(",").map((cell) => cell.trim());
    if (cells.length !== 5) {
      throw new MoneyError(`line ${line}: expected 5 columns, got ${cells.length}`);
    }
    const [date = "", account = "", memo = "", amount = "", currency = ""] = cells;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      throw new MoneyError(`line ${line}: bad date ${JSON.stringify(date)}`);
    }
    try {
      return { date, account, memo, amount: parseMoney(amount, currency) };
    } catch (error) {
      if (error instanceof MoneyError) {
        throw new MoneyError(`line ${line}: ${error.message}`);
      }
      throw error;
    }
  });
}
