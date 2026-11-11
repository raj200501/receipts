/** Command line: ``dueby due|schedule|status|between ARGS [options]``. */

import { nextBusinessDay, isWeekend, weekdayName } from "./calendar.ts";
import { DEFAULT_CALENDAR, loadCalendar, periodNote } from "./fiscal.ts";
import { instalmentDates } from "./schedule.ts";
import { dueLine, daysText, scheduleLine } from "./report.ts";
import { paymentStatus, daysBetweenDates } from "./status.ts";
import { dueDate, parseTerms, readDate } from "./terms.ts";
import type { CalendarDate } from "../vendor/datekit-2.0.0/datekit.ts";

/** Where the command line writes its output. */
export interface Output {
  out: (text: string) => void;
  err: (text: string) => void;
}

const USAGE = `usage: dueby due INVOICE_DATE TERMS [--business] [--fiscal [--calendar FILE]]
       dueby schedule START_DATE COUNT [--fiscal [--calendar FILE]]
       dueby status AS_OF_DATE INVOICE_DATE TERMS
       dueby between FROM_DATE TO_DATE
dates are YYYY-MM-DD; TERMS is netN, eom, eom+N, or Nm
--fiscal appends the fiscal period; the calendar is data/fiscal-fy2027.json unless --calendar is given
`;

/** The options each command accepts. */
const OPTIONS: Readonly<Record<string, readonly string[]>> = {
  due: ["--business", "--fiscal", "--calendar"],
  schedule: ["--fiscal", "--calendar"],
  status: [],
  between: [],
};

/** How many positional arguments each command takes. */
const ARGUMENTS: Readonly<Record<string, number>> = {
  due: 2,
  schedule: 2,
  status: 3,
  between: 2,
};

/** The options that take a value. */
const VALUE_OPTIONS: ReadonlySet<string> = new Set(["--calendar"]);

class UsageError extends Error {}

type Settings = { flags: Set<string>; calendar: string | null };

function periodFor(settings: Settings): ((date: CalendarDate) => string | null) {
  if (!settings.flags.has("--fiscal")) {
    return () => null;
  }
  const calendar = loadCalendar(settings.calendar ?? DEFAULT_CALENDAR);
  return (date) => periodNote(calendar, date);
}

function runDue(args: string[], settings: Settings): string {
  const invoice = readDate(args[0]);
  const terms = parseTerms(args[1]);
  const period = periodFor(settings);
  let due = dueDate(invoice, terms);
  const notes: string[] = [];
  if (settings.flags.has("--business") && isWeekend(due)) {
    notes.push(`rolled from ${weekdayName(due)}`);
    due = nextBusinessDay(due);
  }
  const fiscal = period(due);
  if (fiscal !== null) {
    notes.push(fiscal);
  }
  return `${dueLine(invoice, args[1], due, notes.length === 0 ? null : notes.join(" "))}\n`;
}

function runSchedule(args: string[], settings: Settings): string {
  const start = readDate(args[0]);
  if (!/^\d+$/.test(args[1])) {
    throw new UsageError(`COUNT must be a whole number, got "${args[1]}"`);
  }
  const dates = instalmentDates(start, Number(args[1]));
  const period = periodFor(settings);
  return dates.map((date, index) => `${scheduleLine(index + 1, date, period(date))}\n`).join("");
}

function runStatus(args: string[]): string {
  const asOf = readDate(args[0]);
  const invoice = readDate(args[1]);
  const due = dueDate(invoice, parseTerms(args[2]));
  return `${args[1]} ${args[2]}: ${paymentStatus(asOf, due)}\n`;
}

function runBetween(args: string[]): string {
  const days = daysBetweenDates(readDate(args[0]), readDate(args[1]));
  return `${daysText(days)}\n`;
}

/** Run the command line; returns the exit status (0 on success, 2 for any error). */
export function main(argv: string[], io: Output): number {
  const command = argv[0];
  if (command === undefined || !(command in OPTIONS)) {
    io.err(USAGE);
    return 2;
  }
  const settings: Settings = { flags: new Set<string>(), calendar: null };
  const args: string[] = [];
  try {
    const items = argv.slice(1);
    for (let index = 0; index < items.length; index += 1) {
      const item = items[index];
      if (item.startsWith("--")) {
        if (!OPTIONS[command].includes(item)) {
          throw new UsageError(`unknown option ${item} for ${command}`);
        }
        settings.flags.add(item);
        if (VALUE_OPTIONS.has(item)) {
          index += 1;
          if (index >= items.length) {
            throw new UsageError(`${item} needs a value`);
          }
          settings.calendar = items[index];
        }
      } else {
        args.push(item);
      }
    }
    if (settings.flags.has("--calendar") && !settings.flags.has("--fiscal")) {
      throw new UsageError("--calendar only applies together with --fiscal");
    }
    if (args.length !== ARGUMENTS[command]) {
      throw new UsageError(`${command} takes ${ARGUMENTS[command]} arguments, got ${args.length}`);
    }
    switch (command) {
      case "due":
        io.out(runDue(args, settings));
        break;
      case "schedule":
        io.out(runSchedule(args, settings));
        break;
      case "status":
        io.out(runStatus(args));
        break;
      default:
        io.out(runBetween(args));
    }
    return 0;
  } catch (error) {
    if (error instanceof Error) {
      io.err(`dueby: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}
