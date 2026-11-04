import assert from "node:assert/strict";
import { test } from "node:test";
import { compilePattern, isStatic, matchPattern, parsePattern } from "../src/pattern.ts";

test("a pattern is split into its segments", () => {
  assert.deepEqual(parsePattern("/v2/orders/:orderId/items/*rest"), [
    { kind: "static", value: "v2" },
    { kind: "static", value: "orders" },
    { kind: "param", name: "orderId" },
    { kind: "static", value: "items" },
    { kind: "wildcard", name: "rest" },
  ]);
  assert.deepEqual(parsePattern("/"), []);
});

test("optional parameters may only end a pattern", () => {
  assert.deepEqual(
    parsePattern("/docs/:section?/:page?").map((segment) => segment.kind),
    ["static", "optional", "optional"],
  );
  assert.throws(() => parsePattern("/v2/:year?/reports"), /only optional parameters can follow/);
  assert.throws(() => parsePattern("/v2/:year?/:month"), /only optional parameters can follow/);
});

test("a wildcard must be the last segment", () => {
  assert.throws(() => parsePattern("/v2/files/*path/meta"), /a wildcard must be the last segment/);
});

test("patterns start with a slash, do not end with one, and have no empty segments", () => {
  assert.throws(() => parsePattern("v2/orders"), /it must start with \//);
  assert.throws(() => parsePattern("/v2/orders/"), /it must not end with \//);
  assert.throws(() => parsePattern("/v2//orders"), /it has an empty segment/);
});

test("parameter names are checked", () => {
  assert.throws(() => parsePattern("/v2/orders/:"), /bad parameter name ""/);
  assert.throws(() => parsePattern("/v2/:id/items/:id"), /the name id is used twice/);
  assert.throws(() => parsePattern("/v2/ord?ers"), /unexpected character in "ord\?ers"/);
});

test("static patterns have no parameters", () => {
  assert.equal(isStatic(parsePattern("/v2/orders/export")), true);
  assert.equal(isStatic(parsePattern("/v2/orders/:orderId")), false);
  assert.equal(isStatic(parsePattern("/v2/reports/:period?")), false);
});

test("a parameter matches one segment and is percent-decoded", () => {
  const compiled = compilePattern("/v2/customers/:customerId");
  assert.deepEqual(matchPattern(compiled, "/v2/customers/C-77"), { customerId: "C-77" });
  assert.deepEqual(matchPattern(compiled, "/v2/customers/Ada%20L"), { customerId: "Ada L" });
  assert.equal(matchPattern(compiled, "/v2/customers"), null);
  assert.equal(matchPattern(compiled, "/v2/customers/C-77/notes"), null);
});

test("an optional parameter takes its segment when the path has it", () => {
  const compiled = compilePattern("/v2/reports/:period?");
  assert.deepEqual(matchPattern(compiled, "/v2/reports/2026-Q3"), { period: "2026-Q3" });
});

test("a wildcard takes the rest of the path", () => {
  const compiled = compilePattern("/v2/files/*path");
  assert.deepEqual(matchPattern(compiled, "/v2/files/exports/2026/10.csv"), {
    path: "exports/2026/10.csv",
  });
  assert.equal(matchPattern(compiled, "/v2/files"), null);
});

test("static segments match exactly", () => {
  const compiled = compilePattern("/v2/orders/export");
  assert.deepEqual(matchPattern(compiled, "/v2/orders/export"), {});
  assert.equal(matchPattern(compiled, "/v2/Orders/export"), null);
  assert.equal(matchPattern(compiled, "/v2/orders/exports"), null);
});
