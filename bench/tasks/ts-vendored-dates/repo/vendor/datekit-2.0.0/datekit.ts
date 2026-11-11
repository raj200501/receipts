/**
 * datekit 2.0.0: calendar dates without times or time zones.
 *
 * Vendored copy of the platform team's single-file release. Do not edit it here; to
 * upgrade, vendor the new release next to it and switch the imports. CHANGELOG.md lists
 * the changes from 1.x, and README.md describes the API and the fiscal calendar files.
 *
 * A date is a plain object with a 1-based month: month 1 is January. A date that does not
 * exist is an error, and month arithmetic clamps to the last day of the month: one month
 * after January 31 is February 28 (February 29 in a leap year).
 */

export const VERSION = "2.0.0";

/** A calendar date; `month` is 1 for January and 12 for December. */
export interface CalendarDate {
  year: number;
  month: number;
  day: number;
}

/** Every error datekit throws. */
export class DateError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DateError";
  }
}

const MONTHS: readonly string[] = [
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

function toTime(date: CalendarDate): number {
  return Date.UTC(date.year, date.month - 1, date.day);
}

function fromTime(time: number): CalendarDate {
  const value = new Date(time);
  return {
    year: value.getUTCFullYear(),
    month: value.getUTCMonth() + 1,
    day: value.getUTCDate(),
  };
}

function checkMonth(month: number): void {
  if (!Number.isInteger(month) || month < 1 || month > 12) {
    throw new DateError(`no such month: ${month}`);
  }
}

/** True for leap years of the Gregorian calendar. */
export function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

/** Days in a month (`month` is 1-based). */
export function daysInMonth(year: number, month: number): number {
  checkMonth(month);
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** True when the date exists in the calendar. */
export function isValidDate(date: CalendarDate): boolean {
  return (
    Number.isInteger(date.year) &&
    Number.isInteger(date.month) &&
    Number.isInteger(date.day) &&
    date.month >= 1 &&
    date.month <= 12 &&
    date.day >= 1 &&
    date.day <= daysInMonth(date.year, date.month)
  );
}

/** Parse a YYYY-MM-DD date; text in another form or a date that does not exist is a DateError. */
export function parseDate(text: string): CalendarDate {
  const match = ISO_DATE.exec(text);
  if (match === null) {
    throw new DateError(`not a YYYY-MM-DD date: ${JSON.stringify(text)}`);
  }
  const date = { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
  if (!isValidDate(date)) {
    throw new DateError(`no such date: ${JSON.stringify(text)}`);
  }
  return date;
}

/** The short English name of a month ("Jan" for 1). */
export function monthName(month: number): string {
  checkMonth(month);
  return MONTHS[month - 1];
}

/**
 * Format a date. The pattern may use YYYY, MM (two digits), M, DD (two digits), D, and MMM
 * (the short month name); the default pattern is YYYY-MM-DD.
 */
export function formatDate(date: CalendarDate, pattern = "YYYY-MM-DD"): string {
  return pattern.replace(/YYYY|MMM|MM|M|DD|D/g, (token) => {
    switch (token) {
      case "YYYY":
        return String(date.year).padStart(4, "0");
      case "MMM":
        return monthName(date.month);
      case "MM":
        return String(date.month).padStart(2, "0");
      case "M":
        return String(date.month);
      case "DD":
        return String(date.day).padStart(2, "0");
      default:
        return String(date.day);
    }
  });
}

/** The date `days` days later (earlier when negative). */
export function addDays(date: CalendarDate, days: number): CalendarDate {
  return fromTime(toTime(date) + days * DAY_MS);
}

/** The date `months` months later; the day is clamped to the last day of that month. */
export function addMonths(date: CalendarDate, months: number): CalendarDate {
  const index = date.year * 12 + (date.month - 1) + months;
  const year = Math.floor(index / 12);
  const month = index - year * 12 + 1;
  return { year, month, day: Math.min(date.day, daysInMonth(year, month)) };
}

/** The date `years` years later; February 29 becomes February 28 outside leap years. */
export function addYears(date: CalendarDate, years: number): CalendarDate {
  return addMonths(date, 12 * years);
}

/** The last day of the date's month. */
export function endOfMonth(date: CalendarDate): CalendarDate {
  return { year: date.year, month: date.month, day: daysInMonth(date.year, date.month) };
}

/** `to` minus `from`, in days. */
export function daysBetween(from: CalendarDate, to: CalendarDate): number {
  return Math.round((toTime(to) - toTime(from)) / DAY_MS);
}

/** The ISO day of the week: 1 is Monday and 7 is Sunday. */
export function isoWeekday(date: CalendarDate): number {
  return new Date(toTime(date)).getUTCDay() || 7;
}

/** -1, 0, or 1 as `a` is before, on, or after `b`. */
export function compareDates(a: CalendarDate, b: CalendarDate): number {
  return Math.sign(toTime(a) - toTime(b));
}

// ---------------------------------------------------------------------------------------
// Fiscal calendars
// ---------------------------------------------------------------------------------------

/** One period of a fiscal calendar, from `start` to `end` (both included). */
export interface FiscalPeriod {
  label: string;
  start: CalendarDate;
  end: CalendarDate;
}

/** A fiscal year divided into periods. */
export interface FiscalCalendar {
  name: string;
  fiscalYear: string;
  periods: readonly FiscalPeriod[];
}

function text(record: Record<string, unknown>, key: string, where: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new DateError(`${where}: "${key}" must be a non-empty string`);
  }
  return value;
}

/**
 * Build a fiscal calendar from its definition, the parsed JSON of a calendar file:
 *
 *     {"name": "...", "fiscal_year": "FY2025", "end": "2024-11-23",
 *      "periods": [{"label": "FY25-P01", "start": "2024-09-29"}, ...]}
 *
 * Periods are listed in date order. Each one ends the day before the next one starts,
 * and the last one ends on `end`. Anything else is a DateError.
 */
export function fiscalCalendar(definition: unknown): FiscalCalendar {
  if (typeof definition !== "object" || definition === null || Array.isArray(definition)) {
    throw new DateError("a fiscal calendar must be a JSON object");
  }
  const record = definition as Record<string, unknown>;
  const name = text(record, "name", "fiscal calendar");
  const fiscalYear = text(record, "fiscal_year", name);
  const raw = record.periods;
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new DateError(`fiscal calendar ${fiscalYear} lists no periods`);
  }
  const starts = raw.map((item: unknown, index) => {
    const where = `${fiscalYear} period ${index + 1}`;
    if (typeof item !== "object" || item === null) {
      throw new DateError(`${where}: must be an object with a label and a start`);
    }
    const entry = item as Record<string, unknown>;
    return { label: text(entry, "label", where), start: parseDate(text(entry, "start", where)) };
  });
  const end = parseDate(text(record, "end", fiscalYear));
  const periods: FiscalPeriod[] = starts.map((entry, index) => {
    const next = starts[index + 1];
    const last = next === undefined ? end : addDays(next.start, -1);
    if (compareDates(last, entry.start) < 0) {
      throw new DateError(`${fiscalYear} period ${entry.label} ends before it starts`);
    }
    return { label: entry.label, start: entry.start, end: last };
  });
  const labels = new Set(periods.map((period) => period.label));
  if (labels.size !== periods.length) {
    throw new DateError(`fiscal calendar ${fiscalYear} uses a period label twice`);
  }
  return { name, fiscalYear, periods };
}

/** The period of a calendar that contains `date`, or null when the date is outside it. */
export function fiscalPeriodOf(calendar: FiscalCalendar, date: CalendarDate): FiscalPeriod | null {
  for (const period of calendar.periods) {
    if (compareDates(date, period.start) >= 0 && compareDates(date, period.end) <= 0) {
      return period;
    }
  }
  return null;
}
