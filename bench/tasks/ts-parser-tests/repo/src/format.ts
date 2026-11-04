/** Text for tokens and values: what the command line prints. */

import type { Value } from "./evaluate.ts";
import type { Token } from "./tokens.ts";

/** One line per token: `line:column kind text`, without the end marker. */
export function formatTokens(tokens: readonly Token[]): string {
  return tokens
    .filter((token) => token.kind !== "end")
    .map((token) => `${token.line}:${token.column} ${token.kind.padEnd(8)}${token.text}`)
    .join("\n");
}

/** A value as the command line prints it: strings in quotes, lists and objects as JSON. */
export function formatValue(value: Value): string {
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  return value === null ? "null" : JSON.stringify(value);
}
