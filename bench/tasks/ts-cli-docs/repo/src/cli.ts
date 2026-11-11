import { readFileSync } from "node:fs";
import { parseCents, parseLedger } from "./csv.ts";
import { DataError, UsageError } from "./errors.ts";
import { formatCents } from "./format.ts";
import { convertCents, crossRate, loadRates } from "./rates.ts";
import type { GroupBy } from "./summary.ts";
import { largest, renderCategories, renderSummary, renderTop } from "./summary.ts";

export const VERSION = "1.3.0";
export const DEFAULT_RATES = "data/rates.json";

export interface Io {
  out: (text: string) => void;
  err: (text: string) => void;
}

const HELP = `ledgerline ${VERSION} - summarize an expense ledger

Usage: ledgerline <command> [options]

Commands:
  summary <file>               totals per category or month
  top <file>                   the largest expenses
  categories <file>            the categories in a ledger, with counts
  convert <amount> <from> <to> convert an amount between currencies

Run ledgerline --help to see this text and ledgerline --version for the version.
`;

interface Parsed {
  positional: string[];
  options: Map<string, string>;
}

const OPTION_NAMES: Record<string, string> = {
  "--by": "by",
  "--min": "min",
  "-n": "count",
  "--count": "count",
  "--rates": "rates",
};

/** Split arguments into positionals and known options that take a value. */
function parseArgs(args: string[]): Parsed {
  const positional: string[] = [];
  const options = new Map<string, string>();
  for (let i = 0; i < args.length; i++) {
    const arg = args[i] as string;
    if (arg.startsWith("-") && arg.length > 1 && !/^-\d/.test(arg)) {
      const name = OPTION_NAMES[arg];
      if (name === undefined) {
        throw new UsageError(`unknown option ${arg}`);
      }
      const value = args[i + 1];
      if (value === undefined) {
        throw new UsageError(`${arg} needs a value`);
      }
      options.set(name, value);
      i++;
    } else {
      positional.push(arg);
    }
  }
  return { positional, options };
}

function readLedger(path: string | undefined) {
  if (path === undefined) {
    throw new UsageError("missing ledger file");
  }
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch {
    throw new DataError(`${path}: cannot be read`);
  }
  return parseLedger(text, path);
}

function run(argv: string[], io: Io): void {
  const [command, ...rest] = argv;
  if (command === undefined || command === "--help" || command === "-h") {
    io.out(HELP);
    return;
  }
  if (command === "--version") {
    io.out(`${VERSION}\n`);
    return;
  }
  const { positional, options } = parseArgs(rest);
  switch (command) {
    case "summary": {
      const by = options.get("by") ?? "category";
      if (by !== "category" && by !== "month") {
        throw new UsageError(`--by must be category or month, not ${by}`);
      }
      let expenses = readLedger(positional[0]);
      const min = options.get("min");
      if (min !== undefined) {
        const minCents = parseCents(min);
        expenses = expenses.filter((expense) => expense.cents >= minCents);
      }
      io.out(`${renderSummary(expenses, by as GroupBy)}\n`);
      return;
    }
    case "top": {
      const count = Number(options.get("count") ?? 5);
      if (!Number.isInteger(count) || count < 1) {
        throw new UsageError("-n must be a whole number of 1 or more");
      }
      io.out(`${renderTop(largest(readLedger(positional[0]), count))}\n`);
      return;
    }
    case "categories":
      io.out(`${renderCategories(readLedger(positional[0]))}\n`);
      return;
    case "convert": {
      const [amount, from, to] = positional;
      if (amount === undefined || from === undefined || to === undefined) {
        throw new UsageError("convert needs an amount, a source currency, and a target currency");
      }
      const rates = loadRates(options.get("rates") ?? DEFAULT_RATES);
      const cents = parseCents(amount);
      const converted = convertCents(cents, from.toUpperCase(), to.toUpperCase(), rates);
      const rate = crossRate(from.toUpperCase(), to.toUpperCase(), rates).toFixed(4);
      io.out(
        `${formatCents(cents)} ${from.toUpperCase()} = ${formatCents(converted)} ` +
          `${to.toUpperCase()} (rate ${rate}, rates of ${rates.date})\n`,
      );
      return;
    }
    default:
      throw new UsageError(`unknown command ${command}`);
  }
}

/** Run the command line; returns the exit status (0, or 2 for usage and data errors). */
export function main(argv: string[], io: Io): number {
  try {
    run(argv, io);
    return 0;
  } catch (error) {
    if (error instanceof UsageError || error instanceof DataError) {
      io.err(`ledgerline: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}
