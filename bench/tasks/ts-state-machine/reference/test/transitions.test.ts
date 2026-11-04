import assert from "node:assert/strict";
import { test } from "node:test";
import { run } from "../src/cli.ts";
import { TRANSITIONS } from "../src/transitions.ts";
import { EVENTS, STATES, TransitionError } from "../src/types.ts";
import type { Order } from "../src/types.ts";
import { allowedEvents, createWorkflow } from "../src/workflow.ts";

const NOW = "2027-05-10T12:00:00Z";

const created: Order = {
  id: "SO-1",
  customer: "Test Customer",
  state: "created",
  totalCents: 5000,
  paidCents: 0,
  history: [],
};

test("the table has one row for each combination of state and event", () => {
  const keys = TRANSITIONS.map((row) => `${row.from}/${row.event}`);
  assert.equal(new Set(keys).size, keys.length);
  for (const row of TRANSITIONS) {
    assert.ok(STATES.includes(row.from) && STATES.includes(row.to));
    assert.ok(EVENTS.includes(row.event));
  }
});

test("allowedEvents follows the order of the rows", () => {
  for (const state of STATES) {
    const fromTable = TRANSITIONS.filter((row) => row.from === state).map((row) => row.event);
    assert.deepEqual(allowedEvents(state), fromTable);
  }
});

test("a workflow follows the table it is given", () => {
  const workflow = createWorkflow([
    {
      from: "created",
      event: "pay",
      to: "delivered",
      update: (_order, now) => ({ deliveredAt: now }),
      effects: ["x:one", "x:two"],
    },
    { from: "delivered", event: "refund", to: "created" },
  ]);
  const result = workflow.apply(created, { type: "pay" }, NOW);
  assert.equal(result.order.state, "delivered");
  assert.equal(result.order.deliveredAt, NOW);
  assert.deepEqual(result.effects, ["x:one", "x:two"]);
  assert.deepEqual(workflow.apply(result.order, { type: "refund" }, NOW).effects, []);
  assert.deepEqual(workflow.allowedEvents("created"), ["pay"]);
  assert.deepEqual(workflow.allowedEvents("paid"), []);
});

test("a workflow refuses events without a row and events whose guard refuses", () => {
  const workflow = createWorkflow([
    { from: "created", event: "pay", to: "paid", guard: () => "not today" },
  ]);
  assert.throws(() => workflow.apply(created, { type: "pay" }, NOW), /^TransitionError: not today$/);
  assert.throws(
    () => workflow.apply(created, { type: "cancel" }, NOW),
    (error) => error instanceof TransitionError && error.message === "cannot cancel an order that is created",
  );
});

test("graph prints every row of the table", () => {
  let out = "";
  const status = run(["graph"], { out: (text) => (out += text), err: () => undefined });
  assert.equal(status, 0);
  const lines = out.trimEnd().split("\n");
  assert.equal(lines.length, TRANSITIONS.length);
  assert.equal(lines[0], "created --pay--> paid");
});
