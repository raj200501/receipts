import assert from "node:assert/strict";
import { test } from "node:test";
import { createHandler } from "../src/handler.ts";
import { InventoryStore } from "../src/store.ts";
import type { Item } from "../src/types.ts";

const BOLT: Item = { sku: "BOLT-0042", name: "Hex bolt M8", quantity: 120, price_cents: 35 };
const NUT: Item = { sku: "NUTS-0007", name: "Hex nut M8", quantity: 4, price_cents: 12 };

function seeded() {
  return createHandler({ store: new InventoryStore([BOLT, NUT]) });
}

test("GET /items lists the items ordered by sku", () => {
  const response = seeded()({ method: "GET", path: "/items" });
  assert.equal(response.status, 200);
  assert.deepEqual(response.body, { items: [BOLT, NUT] });
});

test("GET /items?low_stock=10 keeps the items with at most 10 in stock", () => {
  const response = seeded()({ method: "GET", path: "/items", query: { low_stock: "10" } });
  assert.deepEqual(response.body, { items: [NUT] });
});

test("POST /items adds an item and points at it", () => {
  const handle = createHandler();
  const created = handle({ method: "POST", path: "/items", body: BOLT });
  assert.equal(created.status, 201);
  assert.equal(created.headers.location, "/items/BOLT-0042");
  assert.deepEqual(handle({ method: "GET", path: "/items/BOLT-0042" }).body, BOLT);
});

test("POST /items with an existing sku is a conflict", () => {
  const response = seeded()({ method: "POST", path: "/items", body: BOLT });
  assert.equal(response.status, 409);
  assert.deepEqual(response.body, { error: "conflict", sku: "BOLT-0042" });
});

test("GET /items/:sku returns the item", () => {
  const response = seeded()({ method: "GET", path: "/items/NUTS-0007" });
  assert.equal(response.status, 200);
  assert.deepEqual(response.body, NUT);
});

test("PUT /items/:sku replaces the item", () => {
  const handle = seeded();
  const response = handle({
    method: "PUT",
    path: "/items/BOLT-0042",
    body: { name: "Hex bolt M8 zinc", quantity: 90, price_cents: 38 },
  });
  assert.equal(response.status, 200);
  assert.deepEqual(response.body, {
    sku: "BOLT-0042",
    name: "Hex bolt M8 zinc",
    quantity: 90,
    price_cents: 38,
  });
});

test("DELETE /items/:sku removes the item", () => {
  const handle = seeded();
  assert.equal(handle({ method: "DELETE", path: "/items/BOLT-0042" }).status, 204);
  const listed = handle({ method: "GET", path: "/items" });
  assert.deepEqual(listed.body, { items: [NUT] });
});

test("POST /items/:sku/adjust changes the quantity", () => {
  const handle = seeded();
  const response = handle({ method: "POST", path: "/items/BOLT-0042/adjust", body: { delta: -20 } });
  assert.equal(response.status, 200);
  assert.equal((response.body as Item).quantity, 100);
});

test("the handler answers with JSON content type", () => {
  const response = seeded()({ method: "GET", path: "/items" });
  assert.equal(response.headers["content-type"], "application/json");
});
