/** Read a ticket history: one CSV row per day with the number of tickets opened. */

import { formatDay, parseDay } from "./dates.ts";

export const HEADER = "date,tickets";

/** One day of history. */
export interface DayCount {
  /** Day number (days since 1970-01-01, see dates.ts). */
  day: number;
  tickets: number;
}

/** A history that cannot be read; the message names the line. */
export class HistoryError extends Error {
  line: number;

  constructor(line: number, message: string) {
    super(`line ${line}: ${message}`);
    this.name = "HistoryError";
    this.line = line;
  }
}

function parseRow(text: string, line: number, previous: DayCount | undefined): DayCount {
  const fields = text.split(",").map((field) => field.trim());
  if (fields.length !== 2) {
    throw new HistoryError(line, `expected 2 fields, got ${fields.length}`);
  }
  const [dateText, ticketsText] = fields;
  const day = parseDay(dateText);
  if (day === null) {
    throw new HistoryError(line, `not a YYYY-MM-DD date: ${JSON.stringify(dateText)}`);
  }
  if (!/^\d+$/.test(ticketsText)) {
    throw new HistoryError(
      line,
      `tickets must be a whole number of at least 0, got ${JSON.stringify(ticketsText)}`,
    );
  }
  if (previous !== undefined && day <= previous.day) {
    throw new HistoryError(
      line,
      `dates must increase, got ${formatDay(day)} after ${formatDay(previous.day)}`,
    );
  }
  return { day, tickets: Number(ticketsText) };
}

/**
 * Parse the text of a history file. Blank lines are skipped. Dates must increase, but
 * there may be gaps: days when the help desk was closed are simply left out.
 */
export function parseHistory(text: string): DayCount[] {
  const rows: DayCount[] = [];
  let headerSeen = false;
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = index + 1;
    const trimmed = raw.trim();
    if (trimmed === "") {
      return;
    }
    if (!headerSeen) {
      if (trimmed !== HEADER) {
        throw new HistoryError(line, `expected the header "${HEADER}"`);
      }
      headerSeen = true;
      return;
    }
    rows.push(parseRow(trimmed, line, rows.at(-1)));
  });
  if (!headerSeen) {
    throw new HistoryError(1, `expected the header "${HEADER}"`);
  }
  return rows;
}

/** Days between the first and the last day of a history that have no row. */
export function missingDays(history: readonly DayCount[]): number {
  if (history.length === 0) {
    return 0;
  }
  return history[history.length - 1].day - history[0].day + 1 - history.length;
}
