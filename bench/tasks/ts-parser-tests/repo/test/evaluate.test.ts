import assert from "node:assert/strict";
import { test } from "node:test";
import { evaluate, EvalError } from "../src/evaluate.ts";
import type { Value } from "../src/evaluate.ts";
import { parse } from "../src/parser.ts";

function run(source: string, variables: Record<string, Value> = {}): Value {
  return evaluate(parse(source), variables);
}

test("arithmetic follows the usual precedence", () => {
  assert.equal(run("1 + 2 * 3"), 7);
  assert.equal(run("(1 + 2) * 3"), 9);
  assert.equal(run("2 ** 3 ** 2"), 512);
  assert.equal(run("-2 ** 2"), -4);
  assert.equal(run("7 % 4"), 3);
});

test("strings add and compare", () => {
  assert.equal(run('"ab" + "cd"'), "abcd");
  assert.equal(run('"a" == "a"'), true);
  assert.equal(run('"a" != "b"'), true);
});

test("and and or return the operand that decided the result", () => {
  assert.equal(run("0 || 5"), 5);
  assert.equal(run("3 && 4"), 4);
  assert.equal(run("0 and 4"), 0);
});

test("in works on lists and on text", () => {
  assert.equal(run("2 in [1, 2, 3]"), true);
  assert.equal(run('"at" in "cat"'), true);
  assert.equal(run('"x" in ["a"]'), false);
});

test("variables, members, and indexes are looked up", () => {
  const variables = { host: { name: "api-1", tags: ["eu", "prod"] }, count: 4 };
  assert.equal(run("host.name", variables), "api-1");
  assert.equal(run("host.tags[1]", variables), "prod");
  assert.equal(run("count >= 4 ? 'high' : 'low'", variables), "high");
});

test("a conditional only evaluates the branch it takes", () => {
  assert.equal(run("true ? 1 : 1 / 0"), 1);
});

test("problems in the data are evaluation errors", () => {
  assert.throws(() => run("missing"), EvalError);
  assert.throws(() => run("1 / 0"), /division by zero/);
  assert.throws(() => run("[1][3]"), /outside the list/);
  assert.throws(() => run("'a' - 1"), /needs two numbers/);
});
