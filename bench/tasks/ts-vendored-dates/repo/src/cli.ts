/** Command line: ``dueby due|schedule|status|between ARGS [options]``. */

import { nextBusinessDay, isWeekend, weekdayName } from "./calendar.ts";
import { instalmentDates } from "./schedule.ts";
import { dueLine, daysText, scheduleLine } from "./report.ts";
import { paymentStatus, daysBetweenDates } from "./status.ts";
import { dueDate, parseTerms, readDate } from "./terms.ts";

/** Where the command line writes its output. */
export interface Output {
  out: (text: string) => void;
  err: (text: string) => void;
}

const USAGE = `usage: dueby due INVOICE_DATE TERMS [--business]
       dueby schedule START_DATE COUNT
       dueby status AS_OF_DATE INVOICE_DATE TERMS
       dueby between FROM_DATE TO_DATE
dates are YYYY-MM-DD; TERMS is netN, eom, eom+N, or Nm
`;

/** The options each command accepts. */
const OPTIONS: Readonly<Record<string, readonly string[]>> = {
  due: ["--business"],
  schedule: [],
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

class UsageError extends Error {}

function runDue(args: string[], flags: Set<string>): string {
  const invoice = readDate(args[0]);
  const terms = parseTerms(args[1]);
  let due = dueDate(invoice, terms);
  let note: string | null = null;
  if (flags.has("--business") && isWeekend(due)) {
    note = `rolled from ${weekdayName(due)}`;
    due = nextBusinessDay(due);
  }
  return `${dueLine(invoice, args[1], due, note)}\n`;
}

function runSchedule(args: string[]): string {
  const start = readDate(args[0]);
  if (!/^\d+$/.test(args[1])) {
    throw new UsageError(`COUNT must be a whole number, got "${args[1]}"`);
  }
  const dates = instalmentDates(start, Number(args[1]));
  return dates.map((date, index) => `${scheduleLine(index + 1, date, null)}\n`).join("");
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
  const flags = new Set<string>();
  const args: string[] = [];
  try {
    for (const item of argv.slice(1)) {
      if (item.startsWith("--")) {
        if (!OPTIONS[command].includes(item)) {
          throw new UsageError(`unknown option ${item} for ${command}`);
        }
        flags.add(item);
      } else {
        args.push(item);
      }
    }
    if (args.length !== ARGUMENTS[command]) {
      throw new UsageError(`${command} takes ${ARGUMENTS[command]} arguments, got ${args.length}`);
    }
    switch (command) {
      case "due":
        io.out(runDue(args, flags));
        break;
      case "schedule":
        io.out(runSchedule(args));
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
