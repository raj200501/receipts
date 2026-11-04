import assert from "node:assert/strict";
import { test } from "node:test";
import { ERP_SOCKET, erpQuantity, mismatches } from "../src/erpsync.ts";

test("the ERP socket lives under /run", () => {
  assert.ok(ERP_SOCKET.startsWith("/run/"));
});

test("mismatches lists the skus whose counts differ", () => {
  const local = [
    { sku: "BOLT-0042", name: "Hex bolt M8", quantity: 120, price_cents: 35 },
    { sku: "NUTS-0007", name: "Hex nut M8", quantity: 4, price_cents: 12 },
  ];
  assert.deepEqual(mismatches(local, new Map([["BOLT-0042", 120], ["NUTS-0007", 9]])), ["NUTS-0007"]);
});

test("mismatches treats a sku missing from the ERP as different", () => {
  const local = [{ sku: "BOLT-0042", name: "Hex bolt M8", quantity: 1, price_cents: 35 }];
  assert.deepEqual(mismatches(local, new Map()), ["BOLT-0042"]);
});

test("reconciles stock counts with the ERP daemon", async () => {
  // Needs the ERP sync daemon, which only runs on the production hosts.
  assert.equal(await erpQuantity("BOLT-0042"), 120);
});
