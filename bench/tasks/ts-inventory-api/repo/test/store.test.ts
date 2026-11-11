import assert from "node:assert/strict";
import { test } from "node:test";
import { InventoryStore, UnknownSkuError } from "../src/store.ts";
import type { Item } from "../src/types.ts";

const BOLT: Item = { sku: "BOLT-0042", name: "Hex bolt M8", quantity: 120, price_cents: 35 };
const NUT: Item = { sku: "NUTS-0007", name: "Hex nut M8", quantity: 300, price_cents: 12 };

test("a new store is empty", () => {
  const store = new InventoryStore();
  assert.equal(store.size, 0);
  assert.deepEqual(store.list(), []);
});

test("put stores an item and get returns a copy of it", () => {
  const store = new InventoryStore();
  store.put(BOLT);
  const found = store.get("BOLT-0042");
  assert.deepEqual(found, BOLT);
  assert.ok(found);
  found.quantity = 1;
  assert.equal(store.get("BOLT-0042")?.quantity, 120);
});

test("list is ordered by sku", () => {
  const store = new InventoryStore([NUT, BOLT]);
  assert.deepEqual(
    store.list().map((item) => item.sku),
    ["BOLT-0042", "NUTS-0007"],
  );
});

test("put replaces the item stored under the same sku", () => {
  const store = new InventoryStore([BOLT]);
  store.put({ ...BOLT, quantity: 5 });
  assert.equal(store.size, 1);
  assert.equal(store.get("BOLT-0042")?.quantity, 5);
});

test("delete reports whether the item existed", () => {
  const store = new InventoryStore([BOLT]);
  assert.equal(store.delete("BOLT-0042"), true);
  assert.equal(store.delete("BOLT-0042"), false);
  assert.equal(store.has("BOLT-0042"), false);
});

test("adjust adds a positive or negative delta", () => {
  const store = new InventoryStore([BOLT]);
  assert.equal(store.adjust("BOLT-0042", -20).quantity, 100);
  assert.equal(store.adjust("BOLT-0042", 5).quantity, 105);
});

test("adjust throws UnknownSkuError for a sku that is not stocked", () => {
  const store = new InventoryStore();
  assert.throws(() => store.adjust("NOPE-0000", 1), UnknownSkuError);
});
