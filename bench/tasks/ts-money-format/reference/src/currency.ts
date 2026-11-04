/** The currencies the shop trades in. */

import { MoneyError } from "./types.ts";

export interface Currency {
  /** ISO 4217 code. */
  code: string;
  /** The sign printed in front of an amount. */
  symbol: string;
  name: string;
  /** Digits after the decimal point: 2 for dollars, 0 for yen, 3 for dinars. */
  digits: number;
}

export const CURRENCIES: readonly Currency[] = [
  { code: "USD", symbol: "$", name: "US dollar", digits: 2 },
  { code: "EUR", symbol: "€", name: "Euro", digits: 2 },
  { code: "GBP", symbol: "£", name: "Pound sterling", digits: 2 },
  { code: "CAD", symbol: "CA$", name: "Canadian dollar", digits: 2 },
  { code: "JPY", symbol: "¥", name: "Japanese yen", digits: 0 },
  { code: "KRW", symbol: "₩", name: "South Korean won", digits: 0 },
  { code: "KWD", symbol: "KD", name: "Kuwaiti dinar", digits: 3 },
  { code: "BHD", symbol: "BD", name: "Bahraini dinar", digits: 3 },
];

const BY_CODE: ReadonlyMap<string, Currency> = new Map(CURRENCIES.map((c) => [c.code, c]));

/** Look a currency up by its code; the code is case-sensitive. */
export function getCurrency(code: string): Currency {
  const currency = BY_CODE.get(code);
  if (currency === undefined) {
    throw new MoneyError(`unknown currency ${JSON.stringify(code)}`);
  }
  return currency;
}

/** Digits after the decimal point in amounts of this currency. */
export function minorDigits(code: string): number {
  return getCurrency(code).digits;
}
