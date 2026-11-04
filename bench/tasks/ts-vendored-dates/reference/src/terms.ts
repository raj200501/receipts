/** Payment terms and the due dates they give. */

import { addDays, addMonths, endOfMonth, parseDate } from "../vendor/datekit-2.0.0/datekit.ts";
import type { CalendarDate } from "../vendor/datekit-2.0.0/datekit.ts";

/** Payment terms: a number of days, the end of the month plus days, or whole months. */
export type Terms =
  | { kind: "net"; days: number }
  | { kind: "eom"; days: number }
  | { kind: "months"; months: number };

const NET = /^net(\d{1,3})$/;
const EOM = /^eom(?:\+(\d{1,3}))?$/;
const MONTHS = /^(\d{1,2})m$/;

/**
 * Read terms such as `net30` (30 days), `eom` (end of the invoice month), `eom+10` (ten
 * days after the end of the month), or `2m` (two months later). Anything else is an Error.
 */
export function parseTerms(text: string): Terms {
  const net = NET.exec(text);
  if (net !== null) {
    return { kind: "net", days: Number(net[1]) };
  }
  const eom = EOM.exec(text);
  if (eom !== null) {
    return { kind: "eom", days: eom[1] === undefined ? 0 : Number(eom[1]) };
  }
  const months = MONTHS.exec(text);
  if (months !== null) {
    return { kind: "months", months: Number(months[1]) };
  }
  throw new Error(`unknown payment terms: ${JSON.stringify(text)} (use netN, eom, eom+N, or Nm)`);
}

/** The date an invoice written on `invoice` is due under `terms`. */
export function dueDate(invoice: CalendarDate, terms: Terms): CalendarDate {
  switch (terms.kind) {
    case "net":
      return addDays(invoice, terms.days);
    case "eom":
      return addDays(endOfMonth(invoice), terms.days);
    case "months":
      return addMonths(invoice, terms.months);
  }
}

/** Read an invoice date given on the command line; a date that does not exist is an error. */
export function readDate(text: string): CalendarDate {
  return parseDate(text);
}
