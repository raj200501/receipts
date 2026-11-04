import assert from "node:assert/strict";
import { test } from "node:test";
import { EVENTS, STATES, TransitionError } from "../src/types.ts";
import type { Order, OrderState } from "../src/types.ts";
import { allowedEvents, applyEvent } from "../src/workflow.ts";

const NOW = "2027-05-10T12:00:00Z";

function order(state: OrderState, extra: Partial<Order> = {}): Order {
  return {
    id: "SO-1",
    customer: "Test Customer",
    state,
    totalCents: 5000,
    paidCents: state === "created" ? 0 : 5000,
    address: "1 Test Road",
    history: [],
    ...extra,
  };
}

test("pay moves a created order to paid and records the payment", () => {
  const result = applyEvent(order("created"), { type: "pay" }, NOW);
  assert.equal(result.order.state, "paid");
  assert.equal(result.order.paidCents, 5000);
  assert.deepEqual(result.effects, ["email:receipt", "warehouse:pick"]);
});

test("pay needs a total above zero", () => {
  assert.throws(
    () => applyEvent(order("created", { totalCents: 0 }), { type: "pay" }, NOW),
    /^TransitionError: order total is zero$/,
  );
});

test("pack moves a paid order to packed", () => {
  const result = applyEvent(order("paid"), { type: "pack" }, NOW);
  assert.equal(result.order.state, "packed");
  assert.deepEqual(result.effects, ["warehouse:pack"]);
});

test("ship moves a packed order to shipped and books the carrier", () => {
  const result = applyEvent(order("packed"), { type: "ship" }, NOW);
  assert.equal(result.order.state, "shipped");
  assert.deepEqual(result.effects, ["carrier:book", "email:shipped"]);
});

test("ship needs a shipping address", () => {
  const noAddress = order("packed");
  delete noAddress.address;
  assert.throws(() => applyEvent(noAddress, { type: "ship" }, NOW), /no shipping address/);
  assert.throws(
    () => applyEvent(order("packed", { address: "  " }), { type: "ship" }, NOW),
    /no shipping address/,
  );
});

test("deliver stamps the delivery time", () => {
  const result = applyEvent(order("shipped"), { type: "deliver" }, NOW);
  assert.equal(result.order.state, "delivered");
  assert.equal(result.order.deliveredAt, NOW);
  assert.deepEqual(result.effects, ["email:delivered"]);
});

test("return is accepted within 30 days of delivery", () => {
  const delivered = order("delivered", { deliveredAt: "2027-04-12T12:00:00Z" });
  const result = applyEvent(delivered, { type: "return" }, NOW);
  assert.equal(result.order.state, "returned");
  assert.deepEqual(result.effects, ["carrier:return-label", "email:return-approved"]);
});

test("return is refused after 30 days", () => {
  const delivered = order("delivered", { deliveredAt: "2027-04-09T12:00:00Z" });
  assert.throws(
    () => applyEvent(delivered, { type: "return" }, NOW),
    /^TransitionError: return window of 30 days has passed$/,
  );
});

test("cancel releases stock once the order is paid", () => {
  assert.deepEqual(applyEvent(order("created"), { type: "cancel" }, NOW).effects, [
    "email:cancelled",
  ]);
  assert.deepEqual(applyEvent(order("paid"), { type: "cancel" }, NOW).effects, [
    "email:cancelled",
    "warehouse:release",
  ]);
  assert.deepEqual(applyEvent(order("packed"), { type: "cancel" }, NOW).effects, [
    "email:cancelled",
    "warehouse:release",
  ]);
});

test("refund pays back a cancelled paid order and clears the paid amount", () => {
  const result = applyEvent(order("cancelled"), { type: "refund" }, NOW);
  assert.equal(result.order.state, "refunded");
  assert.equal(result.order.paidCents, 0);
  assert.deepEqual(result.effects, ["payments:refund", "email:refund"]);
});

test("refund of an order that was never paid is refused", () => {
  assert.throws(
    () => applyEvent(order("cancelled", { paidCents: 0 }), { type: "refund" }, NOW),
    /nothing was paid for this order/,
  );
});

test("refund works after a return", () => {
  assert.equal(applyEvent(order("returned"), { type: "refund" }, NOW).order.state, "refunded");
});

test("an event the state does not accept is refused with a message", () => {
  assert.throws(
    () => applyEvent(order("shipped"), { type: "cancel" }, NOW),
    (error) => error instanceof TransitionError && error.message === "cannot cancel an order that is shipped",
  );
  assert.throws(
    () => applyEvent(order("refunded"), { type: "refund" }, NOW),
    /cannot refund an order that is refunded/,
  );
});

test("the history gains one entry with the time, states, and note", () => {
  const result = applyEvent(order("created"), { type: "pay", note: "card" }, NOW);
  assert.deepEqual(result.order.history, [
    { at: NOW, from: "created", event: "pay", to: "paid", note: "card" },
  ]);
  const plain = applyEvent(order("paid"), { type: "pack" }, NOW);
  assert.deepEqual(plain.order.history, [{ at: NOW, from: "paid", event: "pack", to: "packed" }]);
});

test("the order passed in is not changed", () => {
  const before = order("created");
  const copy = structuredClone(before);
  applyEvent(before, { type: "pay" }, NOW);
  assert.deepEqual(before, copy);
});

test("allowedEvents lists the events of each state in support's order", () => {
  assert.deepEqual(allowedEvents("created"), ["pay", "cancel"]);
  assert.deepEqual(allowedEvents("packed"), ["ship", "cancel"]);
  assert.deepEqual(allowedEvents("shipped"), ["deliver"]);
  assert.deepEqual(allowedEvents("refunded"), []);
});

test("every event allowed by allowedEvents is accepted in a fitting order", () => {
  for (const state of STATES) {
    for (const type of allowedEvents(state)) {
      const fitting = order(state, { deliveredAt: NOW });
      assert.doesNotThrow(() => applyEvent(fitting, { type }, NOW), `${type} in ${state}`);
    }
  }
});

test("no other event is accepted", () => {
  for (const state of STATES) {
    const allowed = allowedEvents(state);
    for (const type of EVENTS.filter((candidate) => !allowed.includes(candidate))) {
      assert.throws(() => applyEvent(order(state), { type }, NOW), TransitionError, `${type} in ${state}`);
    }
  }
});
