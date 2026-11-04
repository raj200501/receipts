import assert from "node:assert/strict";
import { test } from "node:test";
import { matchRoute, segments } from "../src/router.ts";

test("segments ignores empty parts and a trailing slash", () => {
  assert.deepEqual(segments("/items/ABC/"), ["items", "ABC"]);
  assert.deepEqual(segments("/"), []);
});

test("collection routes", () => {
  assert.deepEqual(matchRoute("GET", "/items"), { name: "list", params: {} });
  assert.deepEqual(matchRoute("POST", "/items"), { name: "create", params: {} });
});

test("item routes carry the sku", () => {
  assert.deepEqual(matchRoute("GET", "/items/BOLT-0042"), {
    name: "get",
    params: { sku: "BOLT-0042" },
  });
  assert.equal(matchRoute("PUT", "/items/BOLT-0042")?.name, "replace");
  assert.equal(matchRoute("DELETE", "/items/BOLT-0042")?.name, "remove");
});

test("adjust route", () => {
  assert.deepEqual(matchRoute("POST", "/items/BOLT-0042/adjust"), {
    name: "adjust",
    params: { sku: "BOLT-0042" },
  });
});

test("the method is case insensitive and skus are decoded", () => {
  assert.equal(matchRoute("get", "/items/A%20B")?.params.sku, "A B");
});

test("other paths and methods match nothing", () => {
  assert.equal(matchRoute("GET", "/orders"), null);
  assert.equal(matchRoute("PATCH", "/items/BOLT-0042"), null);
  assert.equal(matchRoute("DELETE", "/items"), null);
  assert.equal(matchRoute("GET", "/items/A/adjust"), null);
});
