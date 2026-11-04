/** Command line: ``exprlex tokens EXPRESSION`` and ``exprlex eval EXPRESSION [--var NAME=VALUE]...``. */

import { evaluate } from "./evaluate.ts";
import type { Value } from "./evaluate.ts";
import { formatTokens, formatValue } from "./format.ts";
import { LexError, tokenize } from "./tokenizer.ts";
import { ParseError, parse } from "./parser.ts";
import { EvalError } from "./evaluate.ts";

/** Where the command line writes its output. */
export interface Output {
  out: (text: string) => void;
  err: (text: string) => void;
}

const USAGE = `usage: exprlex tokens EXPRESSION
       exprlex eval EXPRESSION [--var NAME=VALUE]...
a VALUE is a number, true, false, null, or text
`;

class UsageError extends Error {}

function variableValue(text: string): Value {
  if (text === "true" || text === "false") {
    return text === "true";
  }
  if (text === "null") {
    return null;
  }
  return text !== "" && Number.isFinite(Number(text)) ? Number(text) : text;
}

/** Run the command line; returns the exit status (0 on success, 2 for any error). */
export function main(argv: string[], io: Output): number {
  const [command, expression, ...rest] = argv;
  if ((command !== "tokens" && command !== "eval") || expression === undefined) {
    io.err(USAGE);
    return 2;
  }
  try {
    if (command === "tokens") {
      if (rest.length > 0) {
        throw new UsageError(`unexpected argument "${rest[0]}"`);
      }
      io.out(`${formatTokens(tokenize(expression))}\n`);
      return 0;
    }
    const variables: Record<string, Value> = {};
    for (let index = 0; index < rest.length; index += 2) {
      const pair = rest[index + 1];
      if (rest[index] !== "--var" || pair === undefined || !pair.includes("=")) {
        throw new UsageError("use --var NAME=VALUE");
      }
      const cut = pair.indexOf("=");
      variables[pair.slice(0, cut)] = variableValue(pair.slice(cut + 1));
    }
    io.out(`${formatValue(evaluate(parse(expression), variables))}\n`);
    return 0;
  } catch (error) {
    if (
      error instanceof UsageError ||
      error instanceof LexError ||
      error instanceof ParseError ||
      error instanceof EvalError
    ) {
      io.err(`exprlex: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}
