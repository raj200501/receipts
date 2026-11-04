import { readFileSync } from "node:fs";
import { parseChangelog } from "./changelog.ts";
import { UsageError } from "./errors.ts";
import { formatProblems, summaryLine } from "./format.ts";
import { lint } from "./rules.ts";

export interface Io {
  out: (text: string) => void;
  err: (text: string) => void;
}

/**
 * Run the command line: changelog-lint [FILE] [--max-problems N]. FILE defaults to
 * CHANGELOG.md. Exit status: 0 when the file is clean, 1 when problems were found,
 * 2 when the command line or the file cannot be used.
 */
export function main(argv: string[], io: Io): number {
  try {
    let file = "CHANGELOG.md";
    let max = Infinity;
    for (let i = 0; i < argv.length; i++) {
      const arg = argv[i] as string;
      if (arg === "--max-problems") {
        const value = Number(argv[++i]);
        if (!Number.isInteger(value) || value < 1) {
          throw new UsageError("--max-problems needs a whole number of 1 or more");
        }
        max = value;
      } else if (arg.startsWith("-")) {
        throw new UsageError(`unknown option ${arg}`);
      } else {
        file = arg;
      }
    }
    let text: string;
    try {
      text = readFileSync(file, "utf8");
    } catch {
      throw new UsageError(`${file}: cannot be read`);
    }
    const problems = lint(parseChangelog(text));
    if (problems.length > 0) {
      io.out(`${formatProblems(file, problems.slice(0, max))}\n`);
    }
    io.out(`${summaryLine(problems.length)}\n`);
    return problems.length === 0 ? 0 : 1;
  } catch (error) {
    if (error instanceof UsageError) {
      io.err(`changelog-lint: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}
