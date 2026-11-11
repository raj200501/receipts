/** The tokenizer: source text in, a list of tokens out. */

import { ESCAPES, KEYWORDS, OPERATORS_1, OPERATORS_2 } from "./tokens.ts";
import type { Token } from "./tokens.ts";

/** A problem in the source text, with the place where it was found. */
export class LexError extends Error {
  readonly line: number;
  readonly column: number;
  readonly offset: number;

  constructor(message: string, line: number, column: number, offset: number) {
    super(`${message} at line ${line}, column ${column}`);
    this.name = "LexError";
    this.line = line;
    this.column = column;
    this.offset = offset;
  }
}

function isDigit(ch: string | undefined): boolean {
  return ch !== undefined && ch >= "0" && ch <= "9";
}

function isNameStart(ch: string | undefined): boolean {
  return ch !== undefined && ((ch >= "a" && ch <= "z") || (ch >= "A" && ch <= "Z") || ch === "_");
}

function isNameChar(ch: string | undefined): boolean {
  return isNameStart(ch) || isDigit(ch);
}

/**
 * Split an expression into tokens. Whitespace and `#` comments (up to the end of the line)
 * separate tokens and are not returned. The result always ends with an `end` token.
 * Anything the language does not know is a LexError.
 */
export function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;
  let line = 1;
  let lineStart = 0;

  const columnOf = (offset: number): number => offset - lineStart + 1;
  const fail = (message: string, offset: number): never => {
    throw new LexError(message, line, columnOf(offset), offset);
  };
  const push = (kind: Token["kind"], start: number, text: string, value: Token["value"]): void => {
    tokens.push({ kind, text, value, offset: start, line, column: columnOf(start) });
  };

  while (pos < source.length) {
    const ch = source[pos];

    if (ch === "\n") {
      pos += 1;
      line += 1;
      lineStart = pos;
      continue;
    }
    if (ch === " " || ch === "\t" || ch === "\r") {
      pos += 1;
      continue;
    }
    if (ch === "#") {
      while (pos < source.length && source[pos] !== "\n") {
        pos += 1;
      }
      continue;
    }

    const start = pos;

    if (isDigit(ch) || (ch === "." && isDigit(source[pos + 1]))) {
      while (isDigit(source[pos])) {
        pos += 1;
      }
      if (source[pos] === "." && isDigit(source[pos + 1])) {
        pos += 1;
        while (isDigit(source[pos])) {
          pos += 1;
        }
      }
      if (source[pos] === "e" || source[pos] === "E") {
        let probe = pos + 1;
        if (source[probe] === "+" || source[probe] === "-") {
          probe += 1;
        }
        if (isDigit(source[probe])) {
          pos = probe;
          while (isDigit(source[pos])) {
            pos += 1;
          }
        }
      }
      if (isNameChar(source[pos])) {
        fail(`invalid number "${source.slice(start, pos + 1)}"`, start);
      }
      const text = source.slice(start, pos);
      push("number", start, text, Number(text));
      continue;
    }

    if (ch === '"' || ch === "'") {
      let value = "";
      pos += 1;
      for (;;) {
        const next = source[pos];
        if (next === undefined || next === "\n") {
          fail("unterminated string", start);
        }
        if (next === ch) {
          pos += 1;
          break;
        }
        if (next === "\\") {
          const code = source[pos + 1];
          const decoded = code === undefined ? undefined : ESCAPES[code];
          if (decoded === undefined) {
            fail(`unknown escape "\\${code ?? ""}"`, pos);
          }
          value += decoded;
          pos += 2;
          continue;
        }
        value += next;
        pos += 1;
      }
      push("string", start, source.slice(start, pos), value);
      continue;
    }

    if (isNameStart(ch)) {
      while (isNameChar(source[pos])) {
        pos += 1;
      }
      const text = source.slice(start, pos);
      push(KEYWORDS.has(text) ? "keyword" : "name", start, text, null);
      continue;
    }

    const pair = source.slice(pos, pos + 2);
    if (OPERATORS_2.has(pair)) {
      pos += 2;
      push("operator", start, pair, null);
      continue;
    }
    if (OPERATORS_1.has(ch)) {
      pos += 1;
      push("operator", start, ch, null);
      continue;
    }
    if (ch === "=") {
      fail('unexpected character "=" (did you mean "=="?)', pos);
    }
    fail(`unexpected character "${ch}"`, pos);
  }

  tokens.push({ kind: "end", text: "", value: null, offset: pos, line, column: columnOf(pos) });
  return tokens;
}
