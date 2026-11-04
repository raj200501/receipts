/** Text for dates: the lines the commands print. */

import { formatDate, monthName } from "../vendor/datekit-2.0.0/datekit.ts";
import type { CalendarDate } from "../vendor/datekit-2.0.0/datekit.ts";
import { weekdayName } from "./calendar.ts";

/** A date as people write it in letters: `2 Mar 2027`. */
export function longDate(date: CalendarDate): string {
  return `${date.day} ${monthName(date.month)} ${date.year}`;
}

/** The line `due` prints; `note` is appended when given. */
export function dueLine(
  invoice: CalendarDate,
  termsText: string,
  due: CalendarDate,
  note: string | null,
): string {
  const base = `${formatDate(invoice)} ${termsText} -> ${formatDate(due)} ${weekdayName(due)} (${longDate(due)})`;
  return note === null ? base : `${base} ${note}`;
}

/** The line `schedule` prints for the instalment with the given 1-based number. */
export function scheduleLine(number: number, date: CalendarDate, note: string | null): string {
  const base = `${String(number).padStart(2, " ")}  ${formatDate(date)} ${weekdayName(date)}`;
  return note === null ? base : `${base} ${note}`;
}

/** Days as text: `1 day`, `0 days`, `-3 days`. */
export function daysText(days: number): string {
  return Math.abs(days) === 1 ? `${days} day` : `${days} days`;
}
