/** Command line: ``ticketcast fit|forecast|backtest FILE [options]``. */

import { readFileSync } from "node:fs";
import { backtest } from "./backtest.ts";
import { ForecastError, fitModel, forecast } from "./forecast.ts";
import { HistoryError, missingDays, parseHistory } from "./history.ts";
import { renderBacktest, renderFit, renderForecast } from "./report.ts";

/** Where the command line writes its output. */
export interface Output {
  out: (text: string) => void;
  err: (text: string) => void;
}

const USAGE = `usage: ticketcast fit FILE [--ridge X]
       ticketcast forecast FILE [--days N] [--ridge X]
       ticketcast backtest FILE [--weeks N] [--ridge X]
`;

/** The options each command accepts. */
const OPTIONS: Readonly<Record<string, readonly string[]>> = {
  fit: ["--ridge"],
  forecast: ["--days", "--ridge"],
  backtest: ["--weeks", "--ridge"],
};

interface Options {
  ridge: number;
  days: number;
  weeks: number;
}

class UsageError extends Error {}

function wholeNumber(name: string, text: string, low: number, high: number): number {
  const value = Number(text);
  if (!/^\d+$/.test(text) || value < low || value > high) {
    throw new UsageError(`${name} must be a whole number from ${low} to ${high}, got "${text}"`);
  }
  return value;
}

function parseOptions(command: string, args: readonly string[]): Options {
  const options: Options = { ridge: 0, days: 14, weeks: 4 };
  for (let i = 0; i < args.length; i += 2) {
    const name = args[i];
    const value = args[i + 1];
    if (!OPTIONS[command].includes(name)) {
      throw new UsageError(`unknown option "${name}" for ${command}`);
    }
    if (value === undefined) {
      throw new UsageError(`${name} needs a value`);
    }
    if (name === "--ridge") {
      const ridge = Number(value);
      if (value.trim() === "" || !Number.isFinite(ridge) || ridge < 0) {
        throw new UsageError(`--ridge must be a number of at least 0, got "${value}"`);
      }
      options.ridge = ridge;
    } else if (name === "--days") {
      options.days = wholeNumber(name, value, 1, 366);
    } else {
      options.weeks = wholeNumber(name, value, 1, 52);
    }
  }
  return options;
}

function run(command: string, text: string, options: Options): string {
  const history = parseHistory(text);
  if (command === "backtest") {
    return renderBacktest(backtest(history, options.weeks, { ridge: options.ridge }));
  }
  const fit = fitModel(history, { ridge: options.ridge });
  if (command === "fit") {
    return renderFit(fit, missingDays(history));
  }
  return renderForecast(fit, forecast(fit.model, options.days));
}

/** Run the command line and return the exit status. */
export function main(argv: readonly string[], output: Output): number {
  const [command, file, ...rest] = argv;
  if (command === undefined || !(command in OPTIONS) || file === undefined) {
    output.err(USAGE);
    return 2;
  }
  let options: Options;
  try {
    options = parseOptions(command, rest);
  } catch (error) {
    if (error instanceof UsageError) {
      output.err(`ticketcast: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
  let text: string;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    output.err(`ticketcast: cannot read ${file}\n`);
    return 2;
  }
  try {
    output.out(run(command, text, options));
  } catch (error) {
    if (error instanceof HistoryError || error instanceof ForecastError) {
      output.err(`ticketcast: ${file}: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
  return 0;
}
