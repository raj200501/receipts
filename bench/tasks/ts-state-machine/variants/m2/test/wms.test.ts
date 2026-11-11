import assert from "node:assert/strict";
import { test } from "node:test";
import type { Order } from "../src/types.ts";
import { buildPickRequest, pushPickRequest } from "../src/wms.ts";

const ORDER: Order = {
  id: "SO-12",
  customer: "Test Customer",
  state: "paid",
  totalCents: 3000,
  paidCents: 3000,
  address: "1 Test Road",
  history: [],
};

test("a pick request carries the order, customer, and address", () => {
  assert.deepEqual(buildPickRequest(ORDER), {
    orderId: "SO-12",
    customer: "Test Customer",
    shipTo: "1 Test Road",
    priority: "normal",
  });
});

test("a rush order is marked", () => {
  assert.equal(buildPickRequest(ORDER, true).priority, "rush");
});

test("an order without an address cannot be picked", () => {
  const { address: _address, ...rest } = ORDER;
  assert.throws(() => buildPickRequest(rest), /order SO-12 has no shipping address/);
});

test("pushes the order to the warehouse system", async () => {
  // Needs WMS_API_TOKEN, which only the CI jobs are given, and the CI network.
  assert.equal(await pushPickRequest(buildPickRequest(ORDER)), 201);
});
