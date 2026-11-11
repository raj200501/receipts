import assert from "node:assert/strict";
import { test } from "node:test";
import { parse, ParseError } from "../src/parser.ts";

test("multiplication binds tighter than addition", () => {
  assert.deepEqual(parse("1 + 2 * 3"), {
    type: "binary",
    op: "+",
    left: { type: "number", value: 1 },
    right: {
      type: "binary",
      op: "*",
      left: { type: "number", value: 2 },
      right: { type: "number", value: 3 },
    },
  });
});

test("the power operator groups to the right", () => {
  const node = parse("2 ** 3 ** 2");
  assert.equal(node.type, "binary");
  assert.deepEqual((node as { right: unknown }).right, {
    type: "binary",
    op: "**",
    left: { type: "number", value: 3 },
    right: { type: "number", value: 2 },
  });
});

test("member access and indexing chain", () => {
  assert.deepEqual(parse("a.b[0]"), {
    type: "index",
    object: { type: "member", object: { type: "name", name: "a" }, name: "b" },
    index: { type: "number", value: 0 },
  });
});

test("a conditional has a test and two branches", () => {
  assert.equal(parse("x ? 1 : 2").type, "conditional");
});

test("not and ! are the same operator", () => {
  assert.deepEqual(parse("not x"), parse("!x"));
});

test("a missing operand is a syntax error with a place", () => {
  assert.throws(() => parse("1 +"), (error: unknown) => {
    assert.ok(error instanceof ParseError);
    assert.match(error.message, /unexpected end of the expression at line 1, column 4/);
    return true;
  });
});

test("an unclosed bracket is a syntax error", () => {
  assert.throws(() => parse("(1 + 2"), /expected "\)"/);
});

test("lexical errors pass through the parser", () => {
  assert.throws(() => parse("1 @ 2"), /unexpected character "@"/);
});
