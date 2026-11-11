import assert from "node:assert/strict";
import { test } from "node:test";
import { delimiterOption, resolveDialect } from "../src/dialect.ts";

test("the default delimiter is a comma", () => {
  assert.deepEqual(resolveDialect(), { delimiter: "," });
  assert.deepEqual(resolveDialect({ delimiter: ";" }), { delimiter: ";" });
});

test("the delimiter must be one character", () => {
  assert.throws(() => resolveDialect({ delimiter: ";;" }), {
    name: "DialectError",
    message: 'the delimiter must be one character, got ";;"',
  });
});

test("the quote and line breaks cannot be the delimiter", () => {
  assert.throws(() => resolveDialect({ delimiter: '"' }), /cannot be the double quote/);
  assert.throws(() => resolveDialect({ delimiter: "\n" }), /cannot be a line break/);
});

test("tab can be named on the command line", () => {
  assert.equal(delimiterOption("tab"), "\t");
  assert.equal(delimiterOption("\\t"), "\t");
  assert.equal(delimiterOption("|"), "|");
});
