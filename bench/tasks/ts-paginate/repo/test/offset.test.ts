import assert from "node:assert/strict";
import { test } from "node:test";
import { paginate } from "../src/offset.ts";

const ITEMS = Array.from({ length: 45 }, (_, index) => index + 1);

test("paginate returns the first page by default", () => {
  const result = paginate(ITEMS);
  assert.equal(result.items.length, 20);
  assert.equal(result.items[0], 1);
  assert.deepEqual(
    [result.page, result.perPage, result.total, result.totalPages],
    [1, 20, 45, 3],
  );
  assert.equal(result.hasNext, true);
  assert.equal(result.hasPrev, false);
});

test("paginate returns the requested page", () => {
  const result = paginate(ITEMS, { page: 2, perPage: 10 });
  assert.deepEqual(result.items, [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]);
  assert.equal(result.hasNext, true);
  assert.equal(result.hasPrev, true);
});

test("the last page may be short and has no next page", () => {
  const result = paginate(ITEMS, { page: 3 });
  assert.equal(result.items.length, 5);
  assert.equal(result.hasNext, false);
});

test("a page past the end is empty", () => {
  const result = paginate(ITEMS, { page: 9 });
  assert.deepEqual(result.items, []);
  assert.equal(result.hasNext, false);
  assert.equal(result.hasPrev, true);
});

test("an empty list has one empty page", () => {
  const result = paginate([]);
  assert.deepEqual([result.items, result.total, result.totalPages], [[], 0, 1]);
  assert.equal(result.hasNext, false);
});

test("paginate cuts a large perPage down to 100", () => {
  assert.equal(paginate(Array.from({ length: 300 }, (_, i) => i), { perPage: 250 }).perPage, 100);
});

test("paginate rejects a page that is not a whole number of at least 1", () => {
  assert.throws(() => paginate(ITEMS, { page: 0 }), RangeError);
  assert.throws(() => paginate(ITEMS, { page: 1.5 }), RangeError);
});

test("paginate does not change its input", () => {
  const copy = [...ITEMS];
  paginate(copy, { page: 2, perPage: 5 });
  assert.deepEqual(copy, ITEMS);
});
