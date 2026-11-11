import assert from "node:assert/strict";
import { test } from "node:test";
import { formatHistory, summarize } from "../src/history.ts";

test("an empty history says so", () => {
  assert.equal(formatHistory([]), "no history\n");
});

test("history is one line per entry, oldest first", () => {
  assert.equal(
    formatHistory([
      { at: "2027-05-03T10:00:00Z", from: "created", event: "pay", to: "paid" },
      { at: "2027-05-04T08:00:00Z", from: "paid", event: "pack", to: "packed", note: "gift wrap" },
    ]),
    "2027-05-03T10:00:00Z  created -> paid  (pay)\n" +
      "2027-05-04T08:00:00Z  paid -> packed  (pack)  # gift wrap\n",
  );
});

test("the summary shows state, amounts, and the address", () => {
  assert.equal(
    summarize({
      id: "SO-9",
      customer: "Test Customer",
      state: "paid",
      totalCents: 4590,
      paidCents: 4590,
      address: "1 Test Road",
      history: [],
    }),
    "order SO-9 for Test Customer\nstate: paid\ntotal: 45.90, paid: 45.90\nship to: 1 Test Road\n",
  );
});

test("the summary shows the delivery time when there is one", () => {
  const text = summarize({
    id: "SO-9",
    customer: "Test Customer",
    state: "delivered",
    totalCents: 100,
    paidCents: 100,
    deliveredAt: "2027-05-10T14:30:00Z",
    history: [],
  });
  assert.match(text, /delivered: 2027-05-10T14:30:00Z\n$/);
});
