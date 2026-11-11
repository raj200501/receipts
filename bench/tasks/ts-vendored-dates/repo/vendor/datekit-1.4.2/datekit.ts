/**
 * datekit 1.4.2: calendar dates without times or time zones.
 *
 * Vendored copy of the platform team's single-file release. Do not edit it here; to
 * upgrade, vendor the new release next to it and switch the imports.
 *
 * A date is a plain object with a 0-based month, as in JavaScript's Date: month 0 is
 * January. Arithmetic works like Date arithmetic, so a day of the month that does not
 * exist rolls over into the next month: one month after January 31 is March 3 (March 2
 * in a leap year), and parseDate reads 2027-02-30 as 2027-03-02.
 */

export const VERSION = "1.4.2";

/** A calendar date; `month` is 0 for January and 11 for December. */
export interface DateParts {
  year: number;
  month: number;
  day: number;
}

/** Short English month names, indexed by the 0-based month. */
export const MONTH_NAMES: readonly string[] = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DAY_MS = 86_400_000;

function toTime(date: DateParts): number {
  return Date.UTC(date.year, date.month, date.day);
}

function fromTime(time: number): DateParts {
  const value = new Date(time);
  return { year: value.getUTCFullYear(), month: value.getUTCMonth(), day: value.getUTCDate() };
}

/** True for leap years of the Gregorian calendar. */
export function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

/** Days in a month (`month` is 0-based). */
export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
}

/**
 * Parse a YYYY-MM-DD date. Text in another form throws an Error. Months and days out
 * of range roll over: 2027-02-30 is 2027-03-02 and 2027-13-01 is 2028-01-01.
 */
export function parseDate(text: string): DateParts {
  const match = ISO_DATE.exec(text);
  if (match === null) {
    throw new Error(`datekit: not a YYYY-MM-DD date: ${JSON.stringify(text)}`);
  }
  return fromTime(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

/** Format a date as YYYY-MM-DD. */
export function formatDate(date: DateParts): string {
  const year = String(date.year).padStart(4, "0");
  const month = String(date.month + 1).padStart(2, "0");
  const day = String(date.day).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** The date `days` days later (earlier when negative). */
export function addDays(date: DateParts, days: number): DateParts {
  return fromTime(toTime(date) + days * DAY_MS);
}

/** The date `months` months later; a day that does not exist rolls over. */
export function addMonths(date: DateParts, months: number): DateParts {
  return fromTime(Date.UTC(date.year, date.month + months, date.day));
}

/** `a` minus `b`, in days. */
export function diffDays(a: DateParts, b: DateParts): number {
  return Math.round((toTime(a) - toTime(b)) / DAY_MS);
}

/** The day of the week: 0 is Sunday, 1 is Monday, and 6 is Saturday. */
export function weekday(date: DateParts): number {
  return new Date(toTime(date)).getUTCDay();
}

/** Negative, zero, or positive as `a` is before, on, or after `b`. */
export function compareDates(a: DateParts, b: DateParts): number {
  return toTime(a) - toTime(b);
}
