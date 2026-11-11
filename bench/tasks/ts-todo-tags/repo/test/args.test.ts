import assert from "node:assert/strict";
import { test } from "node:test";
import { ArgError, lastValue, parseArgs } from "../src/args.ts";

const SPEC = { values: ["file", "due"], flags: ["open"] };

test("parseArgs separates words, flags, and option values", () => {
  const parsed = parseArgs(["add", "Pay", "rent", "--due", "2026-11-30", "--open"], SPEC);
  assert.deepEqual(parsed.positional, ["add", "Pay", "rent"]);
  assert.equal(lastValue(parsed, "due"), "2026-11-30");
  assert.ok(parsed.flags.has("open"));
});

test("parseArgs accepts --name=value", () => {
  const parsed = parseArgs(["list", "--file=work.json"], SPEC);
  assert.equal(lastValue(parsed, "file"), "work.json");
});

test("parseArgs keeps every value of a repeated option", () => {
  const parsed = parseArgs(["--due", "a", "--due", "b"], SPEC);
  assert.deepEqual(parsed.values.get("due"), ["a", "b"]);
  assert.equal(lastValue(parsed, "due"), "b");
});

test("parseArgs rejects an unknown option", () => {
  assert.throws(() => parseArgs(["--colour"], SPEC), ArgError);
});

test("parseArgs rejects an option without its value", () => {
  assert.throws(() => parseArgs(["add", "x", "--due"], SPEC), /--due needs a value/);
});
