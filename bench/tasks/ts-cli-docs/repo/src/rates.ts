import { readFileSync } from "node:fs";
import { DataError } from "./errors.ts";

/** Exchange rates: units of each currency per one unit of the base currency. */
export interface Rates {
  base: string;
  date: string;
  rates: Record<string, number>;
}

/** Read a rates file ({"base", "date", "rates": {"EUR": 0.92, ...}}). */
export function loadRates(path: string): Rates {
  let data: unknown;
  try {
    data = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    const reason = error instanceof SyntaxError ? "not valid JSON" : "cannot be read";
    throw new DataError(`${path}: ${reason}`);
  }
  const record = data as Partial<Rates> | null;
  const table = record?.rates;
  if (typeof table !== "object" || table === null || Object.keys(table).length === 0) {
    throw new DataError(`${path}: no exchange rates in this file`);
  }
  return { base: String(record?.base ?? ""), date: String(record?.date ?? ""), rates: table };
}

/** Convert an amount (in cents) between two currencies listed in the rates. */
export function convertCents(cents: number, from: string, to: string, rates: Rates): number {
  const fromRate = rates.rates[from];
  const toRate = rates.rates[to];
  if (fromRate === undefined) {
    throw new DataError(`no rate for ${from}`);
  }
  if (toRate === undefined) {
    throw new DataError(`no rate for ${to}`);
  }
  return Math.round((cents / fromRate) * toRate);
}

/** The rate from one currency to another, for display. */
export function crossRate(from: string, to: string, rates: Rates): number {
  const fromRate = rates.rates[from];
  const toRate = rates.rates[to];
  if (fromRate === undefined || toRate === undefined) {
    throw new DataError(`no rate for ${fromRate === undefined ? from : to}`);
  }
  return toRate / fromRate;
}
