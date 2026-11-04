/** The currencies the shop trades in. */

import { MoneyError } from "./types.ts";

export interface Currency {
  /** ISO 4217 code. */
  code: string;
  /** The sign printed in front of an amount. */
  symbol: string;
  name: string;
}

export const CURRENCIES: readonly Currency[] = [
  { code: "USD", symbol: "$", name: "US dollar" },
  { code: "EUR", symbol: "€", name: "Euro" },
  { code: "GBP", symbol: "£", name: "Pound sterling" },
  { code: "CAD", symbol: "CA$", name: "Canadian dollar" },
  { code: "JPY", symbol: "¥", name: "Japanese yen" },
  { code: "KRW", symbol: "₩", name: "South Korean won" },
  { code: "KWD", symbol: "KD", name: "Kuwaiti dinar" },
  { code: "BHD", symbol: "BD", name: "Bahraini dinar" },
];

/** Number of digits after the decimal point in every amount, whatever the currency. */
export const MINOR_DIGITS = 2;

const BY_CODE: ReadonlyMap<string, Currency> = new Map(CURRENCIES.map((c) => [c.code, c]));

/** Look a currency up by its code; the code is case-sensitive. */
export function getCurrency(code: string): Currency {
  const currency = BY_CODE.get(code);
  if (currency === undefined) {
    throw new MoneyError(`unknown currency ${JSON.stringify(code)}`);
  }
  return currency;
}
