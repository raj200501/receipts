/**
 * Calendar days as whole numbers (days since 1970-01-01), so that date arithmetic is
 * exact and never depends on the local time zone.
 */

const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;
const MS_PER_DAY = 86_400_000;

/** Short weekday names, Monday first; the index is what weekdayOf returns. */
export const WEEKDAYS: readonly string[] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Parse a YYYY-MM-DD date; returns null when the text is not a real calendar day. */
export function parseDay(text: string): number | null {
  const match = ISO_DAY.exec(text);
  if (match === null) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null;
  }
  return date.getTime() / MS_PER_DAY;
}

/** Format a day number as YYYY-MM-DD. */
export function formatDay(day: number): string {
  return new Date(day * MS_PER_DAY).toISOString().slice(0, 10);
}

/** The weekday of a day number: 0 is Monday, 6 is Sunday. */
export function weekdayOf(day: number): number {
  // Day 0, 1970-01-01, was a Thursday (index 3).
  return (((day + 3) % 7) + 7) % 7;
}

/** The Monday on or before a day. */
export function mondayOf(day: number): number {
  return day - weekdayOf(day);
}
