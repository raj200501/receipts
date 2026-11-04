import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_PER_PAGE, MAX_PER_PAGE, resolveSize } from "../src/limits.ts";

test("resolveSize uses the default when no size is given", () => {
  assert.equal(resolveSize(undefined), DEFAULT_PER_PAGE);
  assert.equal(DEFAULT_PER_PAGE, 20);
});

test("resolveSize keeps a size within the limit", () => {
  assert.equal(resolveSize(1), 1);
  assert.equal(resolveSize(55), 55);
  assert.equal(resolveSize(MAX_PER_PAGE), MAX_PER_PAGE);
});

test("resolveSize cuts a larger size down to the limit", () => {
  assert.equal(resolveSize(101), 100);
  assert.equal(resolveSize(100_000), 100);
});

test("resolveSize rejects sizes that are not whole numbers of at least 1", () => {
  for (const bad of [0, -5, 2.5, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.throws(() => resolveSize(bad), RangeError, String(bad));
  }
});
