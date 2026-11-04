import assert from "node:assert/strict";
import { test } from "node:test";
import { formatTokens, formatValue } from "../src/format.ts";
import { tokenize } from "../src/tokenizer.ts";

test("formatTokens prints one line per token without the end marker", () => {
  assert.equal(formatTokens(tokenize("a >= 2")), "1:1 name    a\n1:3 operator>=\n1:6 number  2");
});

test("formatTokens of an empty expression is empty", () => {
  assert.equal(formatTokens(tokenize("")), "");
});

test("formatValue quotes strings and writes lists as JSON", () => {
  assert.equal(formatValue("hi"), '"hi"');
  assert.equal(formatValue([1, "a", null]), '[1,"a",null]');
  assert.equal(formatValue(null), "null");
  assert.equal(formatValue(2.5), "2.5");
});
