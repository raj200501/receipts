import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { createHandler } from "../src/handler.ts";
import { InventoryStore } from "../src/store.ts";

const BOLT = { sku: "BOLT-0042", name: "Hex bolt M8", quantity: 120, price_cents: 35 };

function handler() {
  const dir = mkdtempSync(join(tmpdir(), "stockroom-bins-"));
  const path = join(dir, "locations.json");
  writeFileSync(path, JSON.stringify({ locations: [] }));
  return createHandler({ store: new InventoryStore([BOLT]), locationsPath: path });
}

test("GET of an unknown sku is a 404", () => {
  const response = handler()({ method: "GET", path: "/items/NOPE-0000" });
  assert.equal(response.status, 404);
  assert.equal((response.body as { error: string }).error, "not_found");
});

test("PUT of an unknown sku is a 404 and creates nothing", () => {
  const handle = handler();
  const body = { name: "Washer", quantity: 1, price_cents: 2 };
  assert.equal(handle({ method: "PUT", path: "/items/WASH-0001", body }).status, 404);
  assert.equal(handle({ method: "GET", path: "/items/WASH-0001" }).status, 404);
});

test("DELETE of an unknown sku is a 404", () => {
  assert.equal(handler()({ method: "DELETE", path: "/items/NOPE-0000" }).status, 404);
});

test("adjust of an unknown sku is a 404", () => {
  const response = handler()({ method: "POST", path: "/items/NOPE-0000/adjust", body: { delta: 1 } });
  assert.equal(response.status, 404);
});

test("an unknown route is a 404 no_such_route", () => {
  const handle = handler();
  for (const [method, path] of [["GET", "/orders"], ["PATCH", "/items/BOLT-0042"], ["GET", "/"]]) {
    const response = handle({ method: method as string, path: path as string });
    assert.equal(response.status, 404);
    assert.equal((response.body as { error: string }).error, "no_such_route");
  }
});
