import assert from "node:assert/strict";
import { test } from "node:test";
import { publishRoutes, routeTable, serviceName } from "../src/sidecar.ts";
import type { RouteDefinition } from "../src/types.ts";

const ROUTES: RouteDefinition[] = [
  {
    name: "invoices.get",
    method: "GET",
    pattern: "/v2/invoices/:invoiceId",
    upstream: "http://billing-api.prod.internal:8080",
  },
  {
    name: "media.download",
    method: "GET",
    pattern: "/v2/media/*path",
    upstream: "http://media-store.prod.internal:8080",
  },
];

test("the route table lists every route once, in manifest order", () => {
  const table = routeTable(ROUTES);
  assert.equal(table.kind, "route-table");
  assert.deepEqual(
    table.routes.map((route) => route.name),
    ["invoices.get", "media.download"],
  );
});

test("published routes keep their method and pattern", () => {
  const [invoices] = routeTable(ROUTES).routes;
  assert.deepEqual(invoices, {
    name: "invoices.get",
    method: "GET",
    pattern: "/v2/invoices/:invoiceId",
    service: "billing-api",
  });
});

test("the service name is the first label of the upstream host", () => {
  assert.equal(serviceName("https://search.prod.internal:9443"), "search");
  assert.equal(serviceName("http://billing-api.prod.internal:8080/v1"), "billing-api");
});

test("publishes the route table to the mesh sidecar", async () => {
  // Needs the sidecar's admin socket (/run/mesh/sidecar-admin.sock), which only edge nodes have.
  assert.equal(await publishRoutes(routeTable(ROUTES)), "ok");
});
