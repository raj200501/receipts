/** Weekdays and business days. */

import { addDays, weekday } from "../vendor/datekit-1.4.2/datekit.ts";
import type { DateParts } from "../vendor/datekit-1.4.2/datekit.ts";

const WEEKDAY_NAMES: readonly string[] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** The short name of the day of the week of a date. */
export function weekdayName(date: DateParts): string {
  return WEEKDAY_NAMES[weekday(date)];
}

/** True for Saturdays and Sundays. */
export function isWeekend(date: DateParts): boolean {
  const day = weekday(date);
  return day === 0 || day === 6;
}

/** A Saturday or Sunday moves on to the Monday after it; other days stay. */
export function nextBusinessDay(date: DateParts): DateParts {
  const day = weekday(date);
  if (day === 6) {
    return addDays(date, 2);
  }
  if (day === 0) {
    return addDays(date, 1);
  }
  return date;
}
