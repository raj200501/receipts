import assert from "node:assert/strict";
import { test } from "node:test";
import * as pager from "../src/index.ts";

test("the package exports the page-number helpers", () => {
  for (const name of ["paginate", "parsePageParams", "pageLinks", "linkHeader", "resolveSize"]) {
    assert.equal(typeof (pager as Record<string, unknown>)[name], "function", name);
  }
});

test("the package exports the error class and the limits", () => {
  assert.equal(new pager.PageParamsError("x").name, "PageParamsError");
  assert.equal(pager.DEFAULT_PER_PAGE, 20);
  assert.equal(pager.MAX_PER_PAGE, 100);
});
