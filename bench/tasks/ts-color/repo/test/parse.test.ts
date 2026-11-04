import assert from "node:assert/strict";
import { test } from "node:test";
import { ColorError } from "../src/errors.ts";
import { parseColor } from "../src/parse.ts";

test("parseColor reads six-digit hex", () => {
  assert.deepEqual(parseColor("#336699"), { r: 51, g: 102, b: 153 });
});

test("parseColor reads three-digit hex by doubling the digits", () => {
  assert.deepEqual(parseColor("#f80"), { r: 255, g: 136, b: 0 });
});

test("parseColor ignores case and surrounding spaces", () => {
  assert.deepEqual(parseColor("  #AbCdEf "), { r: 171, g: 205, b: 239 });
});

test("parseColor reads rgb() with spaces", () => {
  assert.deepEqual(parseColor("rgb(10,  20, 30)"), { r: 10, g: 20, b: 30 });
});

test("parseColor rejects a channel above 255", () => {
  assert.throws(() => parseColor("rgb(256, 0, 0)"), /above 255/);
});

test("parseColor rejects text that is not a color", () => {
  for (const bad of ["", "red", "#12", "#12345", "#ggg", "rgb(1, 2)", "336699"]) {
    assert.throws(() => parseColor(bad), ColorError, bad);
  }
});
