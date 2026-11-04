import assert from "node:assert/strict";
import { test } from "node:test";
import { describeEffect } from "../src/effects.ts";

test("describes a known effect in words", () => {
  assert.equal(describeEffect("warehouse:pack"), "ask the warehouse to pack the order");
});

test("describes a refund", () => {
  assert.equal(describeEffect("payments:refund"), "refund the customer's payment");
});

test("an unknown effect is described by its name", () => {
  assert.equal(describeEffect("crm:sync"), "crm:sync");
});
