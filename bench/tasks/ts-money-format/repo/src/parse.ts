/** Turning text into Money. */

import { getCurrency, MINOR_DIGITS } from "./currency.ts";
import { MoneyError } from "./types.ts";
import type { Money } from "./types.ts";

const AMOUNT = /^(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?$/;

/**
 * Read an amount such as "1,234.50", "-12", or "$3.40" in the given currency.
 *
 * The currency's own symbol or code may be written with the number. Digits after the
 * decimal point beyond what the currency allows are an error, never rounded away.
 */
export function parseMoney(text: string, currency: string): Money {
  const info = getCurrency(currency);
  let rest = text.trim();
  if (rest === "") {
    throw new MoneyError("empty amount");
  }
  let sign = "";
  if (rest.startsWith("-")) {
    sign = "-";
    rest = rest.slice(1).trim();
  }
  for (const marker of [info.symbol, info.code]) {
    if (rest.startsWith(marker)) {
      rest = rest.slice(marker.length).trim();
    } else if (rest.endsWith(marker)) {
      rest = rest.slice(0, rest.length - marker.length).trim();
    }
  }
  const match = AMOUNT.exec(rest);
  if (match === null) {
    throw new MoneyError(`cannot read amount ${JSON.stringify(text)}`);
  }
  const [, whole = "0", fraction = ""] = match;
  if (fraction.length > MINOR_DIGITS) {
    throw new MoneyError(
      `too many decimal places for ${currency} (at most ${MINOR_DIGITS}): ${JSON.stringify(text)}`,
    );
  }
  const digits = whole.replaceAll(",", "") + fraction.padEnd(MINOR_DIGITS, "0");
  const minor = Number(digits);
  if (!Number.isSafeInteger(minor)) {
    throw new MoneyError(`amount out of range: ${JSON.stringify(text)}`);
  }
  return { minor: sign === "-" && minor !== 0 ? -minor : minor, currency };
}
