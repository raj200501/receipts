import assert from "node:assert/strict";
import { test } from "node:test";
import { PageParamsError } from "../src/errors.ts";
import { parsePageParams } from "../src/params.ts";

test("parsePageParams defaults to page 1 and 20 items", () => {
  assert.deepEqual(parsePageParams({}), { page: 1, perPage: 20 });
});

test("parsePageParams reads page and per_page", () => {
  assert.deepEqual(parsePageParams({ page: "3", per_page: "50" }), { page: 3, perPage: 50 });
});

test("parsePageParams cuts a large per_page down to 100", () => {
  assert.equal(parsePageParams({ per_page: "5000" }).perPage, 100);
});

test("parsePageParams ignores parameters it does not know", () => {
  assert.deepEqual(parsePageParams({ page: "2", sort: "name", q: "x" }), { page: 2, perPage: 20 });
});

test("parsePageParams rejects values that are not positive whole numbers", () => {
  for (const bad of ["0", "-1", "2.5", "abc", "", "1e3"]) {
    assert.throws(() => parsePageParams({ page: bad }), PageParamsError, `page=${bad}`);
    assert.throws(() => parsePageParams({ per_page: bad }), PageParamsError, `per_page=${bad}`);
  }
});

test("the error message names the parameter", () => {
  assert.throws(() => parsePageParams({ per_page: "x" }), /^PageParamsError: per_page must be/);
});
