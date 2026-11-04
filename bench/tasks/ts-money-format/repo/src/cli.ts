/** The moneyfmt command line. */

import { readFileSync } from "node:fs";
import { exportLedger, parseEntries } from "./export.ts";
import { formatMoney } from "./format.ts";
import { formatOrder, parseOrder } from "./order.ts";
import { parseMoney } from "./parse.ts";
import { MoneyError } from "./types.ts";

export interface Io {
  out: (text: string) => void;
  err: (text: string) => void;
}

const USAGE = `usage: moneyfmt <command> [arguments]

  format [--code] <amount> <currency>   print an amount as people read it
  parse <amount> <currency>             print the amount in minor units as JSON
  order <file>                          print an order statement
  export <file>                         print the accounting export of a ledger file
`;

function readFile(path: string): string {
  try {
    return readFileSync(path, "utf8");
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new MoneyError(`cannot read ${path}: ${reason}`);
  }
}

/** Run the command line; returns the exit status (0, or 2 for any problem). */
export function run(argv: readonly string[], io: Io): number {
  const [command, ...args] = argv;
  try {
    if (command === "format") {
      const code = args[0] === "--code";
      const rest = code ? args.slice(1) : args;
      if (rest.length !== 2) {
        throw new MoneyError("format needs an amount and a currency");
      }
      const [amount = "", currency = ""] = rest;
      io.out(`${formatMoney(parseMoney(amount, currency), { style: code ? "code" : "symbol" })}\n`);
      return 0;
    }
    if (command === "parse") {
      if (args.length !== 2) {
        throw new MoneyError("parse needs an amount and a currency");
      }
      const [amount = "", currency = ""] = args;
      io.out(`${JSON.stringify(parseMoney(amount, currency))}\n`);
      return 0;
    }
    if (command === "order" || command === "export") {
      if (args.length !== 1) {
        throw new MoneyError(`${command} needs one file`);
      }
      const text = readFile(args[0] ?? "");
      io.out(command === "order" ? formatOrder(parseOrder(text)) : exportLedger(parseEntries(text)));
      return 0;
    }
    io.err(USAGE);
    return 2;
  } catch (error) {
    if (error instanceof MoneyError) {
      io.err(`moneyfmt: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}
