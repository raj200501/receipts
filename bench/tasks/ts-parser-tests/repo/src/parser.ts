/** The parser: tokens in, a syntax tree out (precedence climbing). */

import { tokenize } from "./tokenizer.ts";
import type { Token } from "./tokens.ts";

/** A node of the syntax tree. */
export type Node =
  | { type: "number"; value: number }
  | { type: "string"; value: string }
  | { type: "literal"; value: boolean | null }
  | { type: "name"; name: string }
  | { type: "member"; object: Node; name: string }
  | { type: "index"; object: Node; index: Node }
  | { type: "list"; items: Node[] }
  | { type: "unary"; op: string; operand: Node }
  | { type: "binary"; op: string; left: Node; right: Node }
  | { type: "conditional"; test: Node; yes: Node; no: Node };

/** A syntax error with the place of the token where parsing stopped. */
export class ParseError extends Error {
  constructor(message: string, token: Token) {
    super(`${message} at line ${token.line}, column ${token.column}`);
    this.name = "ParseError";
  }
}

/** Binary operators by binding power; a higher number binds tighter. */
const BINARY: Readonly<Record<string, number>> = {
  "||": 1,
  or: 1,
  "&&": 2,
  and: 2,
  "==": 3,
  "!=": 3,
  "<": 4,
  "<=": 4,
  ">": 4,
  ">=": 4,
  in: 4,
  "+": 5,
  "-": 5,
  "*": 6,
  "/": 6,
  "%": 6,
  "**": 8,
};

const UNARY_POWER = 7;
const RIGHT_ASSOCIATIVE: ReadonlySet<string> = new Set(["**"]);

class Parser {
  private index = 0;
  private readonly tokens: Token[];

  constructor(tokens: Token[]) {
    this.tokens = tokens;
  }

  private peek(): Token {
    return this.tokens[this.index];
  }

  private next(): Token {
    const token = this.tokens[this.index];
    if (token.kind !== "end") {
      this.index += 1;
    }
    return token;
  }

  private isOperator(text: string): boolean {
    const token = this.peek();
    return (token.kind === "operator" || token.kind === "keyword") && token.text === text;
  }

  private expect(text: string): void {
    if (!this.isOperator(text)) {
      throw new ParseError(`expected "${text}"`, this.peek());
    }
    this.next();
  }

  parseAll(): Node {
    const node = this.parseConditional();
    if (this.peek().kind !== "end") {
      throw new ParseError(`unexpected "${this.peek().text}"`, this.peek());
    }
    return node;
  }

  private parseConditional(): Node {
    const test = this.parseBinary(0);
    if (!this.isOperator("?")) {
      return test;
    }
    this.next();
    const yes = this.parseConditional();
    this.expect(":");
    const no = this.parseConditional();
    return { type: "conditional", test, yes, no };
  }

  private parseBinary(minPower: number): Node {
    let left = this.parseUnary();
    for (;;) {
      const token = this.peek();
      const power = token.kind === "operator" || token.kind === "keyword" ? BINARY[token.text] : undefined;
      if (power === undefined || power <= minPower) {
        return left;
      }
      this.next();
      const right = this.parseBinary(RIGHT_ASSOCIATIVE.has(token.text) ? power - 1 : power);
      left = { type: "binary", op: token.text, left, right };
    }
  }

  private parseUnary(): Node {
    const token = this.peek();
    if (
      (token.kind === "operator" && (token.text === "!" || token.text === "-")) ||
      (token.kind === "keyword" && token.text === "not")
    ) {
      this.next();
      return { type: "unary", op: token.text === "not" ? "!" : token.text, operand: this.parseBinary(UNARY_POWER) };
    }
    return this.parsePostfix();
  }

  private parsePostfix(): Node {
    let node = this.parsePrimary();
    for (;;) {
      if (this.isOperator(".")) {
        this.next();
        const name = this.next();
        if (name.kind !== "name") {
          throw new ParseError("expected a name after \".\"", name);
        }
        node = { type: "member", object: node, name: name.text };
      } else if (this.isOperator("[")) {
        this.next();
        const index = this.parseConditional();
        this.expect("]");
        node = { type: "index", object: node, index };
      } else {
        return node;
      }
    }
  }

  private parsePrimary(): Node {
    const token = this.next();
    switch (token.kind) {
      case "number":
        return { type: "number", value: token.value as number };
      case "string":
        return { type: "string", value: token.value as string };
      case "name":
        return { type: "name", name: token.text };
      case "keyword":
        if (token.text === "true" || token.text === "false") {
          return { type: "literal", value: token.text === "true" };
        }
        if (token.text === "null") {
          return { type: "literal", value: null };
        }
        throw new ParseError(`unexpected "${token.text}"`, token);
      case "operator":
        if (token.text === "(") {
          const inner = this.parseConditional();
          this.expect(")");
          return inner;
        }
        if (token.text === "[") {
          const items: Node[] = [];
          while (!this.isOperator("]")) {
            items.push(this.parseConditional());
            if (!this.isOperator("]")) {
              this.expect(",");
            }
          }
          this.next();
          return { type: "list", items };
        }
        throw new ParseError(`unexpected "${token.text}"`, token);
      default:
        throw new ParseError("unexpected end of the expression", token);
    }
  }
}

/** Parse an expression; lexical errors (LexError) pass through. */
export function parse(source: string): Node {
  return new Parser(tokenize(source)).parseAll();
}
