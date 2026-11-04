import assert from "node:assert/strict";
import { test } from "node:test";
import { Router } from "../src/router.ts";
import type { RouteDefinition } from "../src/types.ts";

const ROUTES: RouteDefinition[] = [
  { name: "health", method: "GET", pattern: "/healthz", upstream: "http://health.test.invalid", strict: true },
  { name: "customers.get", method: "GET", pattern: "/v2/customers/:customerId", upstream: "http://crm.test.invalid" },
  { name: "customers.update", method: "PATCH", pattern: "/v2/customers/:customerId", upstream: "http://crm.test.invalid" },
  { name: "orders.list", method: "GET", pattern: "/v2/orders", upstream: "http://orders.test.invalid" },
  { name: "orders.create", method: "POST", pattern: "/v2/orders", upstream: "http://orders.test.invalid" },
  { name: "orders.get", method: "GET", pattern: "/v2/orders/:orderId", upstream: "http://orders.test.invalid" },
  { name: "orders.export", method: "GET", pattern: "/v2/orders/export", upstream: "http://batch.test.invalid" },
  { name: "files.get", method: "GET", pattern: "/v2/files/*path", upstream: "http://files.test.invalid" },
];

const router = new Router(ROUTES);

function routeName(method: "GET" | "HEAD" | "POST" | "PATCH" | "DELETE", target: string): string {
  const result = router.match(method, target);
  return result.status === 200 ? result.route.name : String(result.status);
}

test("a static route matches its path", () => {
  assert.deepEqual(router.match("GET", "/v2/orders"), {
    status: 200,
    route: ROUTES[3],
    params: {},
  });
});

test("a route with a parameter gives the parameter value", () => {
  const result = router.match("GET", "/v2/customers/C-77");
  assert.equal(result.status, 200);
  assert.deepEqual(result.status === 200 && result.params, { customerId: "C-77" });
});

test("routes without parameters win over routes with parameters", () => {
  assert.equal(routeName("GET", "/v2/orders/export"), "orders.export");
  assert.equal(routeName("GET", "/v2/orders/A-1001"), "orders.get");
});

test("otherwise the first matching route in manifest order wins", () => {
  const ordered = new Router([
    { name: "first", method: "GET", pattern: "/v2/items/:itemId", upstream: "http://a.test.invalid" },
    { name: "second", method: "GET", pattern: "/v2/items/*rest", upstream: "http://b.test.invalid" },
  ]);
  const result = ordered.match("GET", "/v2/items/7");
  assert.equal(result.status === 200 && result.route.name, "first");
});

test("the method picks between routes with the same pattern", () => {
  assert.equal(routeName("POST", "/v2/orders"), "orders.create");
  assert.equal(routeName("PATCH", "/v2/customers/C-77"), "customers.update");
});

test("a HEAD request is answered by the GET route", () => {
  assert.equal(routeName("HEAD", "/v2/orders"), "orders.list");
});

test("a known path with another method is a 405 with the allowed methods", () => {
  assert.deepEqual(router.match("DELETE", "/v2/customers/C-77"), {
    status: 405,
    allowed: ["GET", "HEAD", "PATCH"],
  });
});

test("an unknown path is a 404", () => {
  assert.deepEqual(router.match("GET", "/v2/invoices"), { status: 404 });
});

test("the query string is ignored", () => {
  assert.equal(routeName("GET", "/v2/orders?limit=5#top"), "orders.list");
});

test("a static route also matches the path with a trailing slash", () => {
  assert.equal(routeName("GET", "/v2/orders/"), "orders.list");
  assert.equal(routeName("GET", "/v2/orders//"), "404");
});

test("a strict route does not match the path with a trailing slash", () => {
  assert.equal(routeName("GET", "/healthz"), "health");
  assert.equal(routeName("GET", "/healthz/"), "404");
});

test("a request target must be a path", () => {
  assert.throws(() => router.match("GET", "v2/orders"), { name: "PathError" });
});
