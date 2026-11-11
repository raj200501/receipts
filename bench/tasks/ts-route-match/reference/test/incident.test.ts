import assert from "node:assert/strict";
import { test } from "node:test";
import { compilePattern, matchPattern } from "../src/pattern.ts";
import { Router } from "../src/router.ts";
import type { RouteDefinition } from "../src/types.ts";

// Regression tests for incident INC-2291: optional parameters and trailing slashes.
const ROUTES: RouteDefinition[] = [
  { name: "reports.overview", method: "GET", pattern: "/v2/reports/:period?", upstream: "https://reports.test.invalid" },
  { name: "orders.get", method: "GET", pattern: "/v2/orders/:orderId", upstream: "http://orders.test.invalid" },
  { name: "orders.lines", method: "GET", pattern: "/v2/orders/:orderId/items", upstream: "http://lines.test.invalid" },
  { name: "files.download", method: "GET", pattern: "/v2/files/*path", upstream: "http://files.test.invalid" },
  { name: "hooks", method: "POST", pattern: "/v2/webhooks/:provider", upstream: "http://hooks.test.invalid", strict: true },
];

const router = new Router(ROUTES);

function params(method: "GET" | "POST", target: string): Record<string, string> | number {
  const result = router.match(method, target);
  return result.status === 200 ? result.params : result.status;
}

test("an optional parameter can be left out", () => {
  assert.deepEqual(params("GET", "/v2/reports"), {});
  assert.deepEqual(params("GET", "/v2/reports/2026-Q3"), { period: "2026-Q3" });
});

test("several optional parameters in a row", () => {
  const compiled = compilePattern("/archive/:year?/:month?");
  assert.deepEqual(matchPattern(compiled, "/archive"), {});
  assert.deepEqual(matchPattern(compiled, "/archive/2024"), { year: "2024" });
  assert.deepEqual(matchPattern(compiled, "/archive/2024/05"), { year: "2024", month: "05" });
  assert.equal(matchPattern(compiled, "/archive/2024/05/07"), null);
  assert.equal(matchPattern(compiled, "/archive//05"), null);
});

test("a trailing slash matches routes with parameters", () => {
  assert.deepEqual(params("GET", "/v2/orders/A-1001/"), { orderId: "A-1001" });
  assert.deepEqual(params("GET", "/v2/orders/A-1001/items/"), { orderId: "A-1001" });
  assert.deepEqual(params("GET", "/v2/reports/2026-Q3/"), { period: "2026-Q3" });
  assert.deepEqual(params("GET", "/v2/reports/"), {});
});

test("the trailing slash is not part of a wildcard value", () => {
  assert.deepEqual(params("GET", "/v2/files/exports/2026-10/"), { path: "exports/2026-10" });
});

test("two trailing slashes do not match", () => {
  assert.equal(params("GET", "/v2/orders/A-1001//"), 404);
  assert.equal(params("GET", "/v2/files/exports//"), 404);
});

test("strict routes with parameters still need the exact path", () => {
  assert.deepEqual(params("POST", "/v2/webhooks/acme"), { provider: "acme" });
  assert.equal(params("POST", "/v2/webhooks/acme/"), 404);
});
