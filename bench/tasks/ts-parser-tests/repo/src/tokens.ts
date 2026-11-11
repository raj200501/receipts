/** Token types and the fixed tables of the expression language. */

/** What a token is. `end` is the marker after the last token. */
export type TokenKind = "number" | "string" | "name" | "keyword" | "operator" | "end";

/** One token with the place where it starts in the source (line and column count from 1). */
export interface Token {
  kind: TokenKind;
  /** The source text of the token; for a string, the text between the quotes as written. */
  text: string;
  /** The value of a number or string token; `null` for the other kinds. */
  value: number | string | null;
  offset: number;
  line: number;
  column: number;
}

/** Words that are not names. */
export const KEYWORDS: ReadonlySet<string> = new Set(["and", "or", "not", "in", "true", "false", "null"]);

/** Operators of two characters; the scanner tries these before the one-character ones. */
export const OPERATORS_2: ReadonlySet<string> = new Set(["**", "==", "!=", "<=", ">=", "&&", "||"]);

/** Operators and punctuation of one character. */
export const OPERATORS_1: ReadonlySet<string> = new Set([
  "+",
  "-",
  "*",
  "/",
  "%",
  "<",
  ">",
  "!",
  "(",
  ")",
  "[",
  "]",
  ",",
  ".",
  "?",
  ":",
]);

/** The characters after a backslash in a string, and what they stand for. */
export const ESCAPES: Readonly<Record<string, string>> = {
  n: "\n",
  t: "\t",
  r: "\r",
  "\\": "\\",
  '"': '"',
  "'": "'",
};
