import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchRates, parseRates } from "../src/rates.ts";

test("reads a rates table", () => {
  const rates = parseRates("USD,1\nEUR,0.92\nJPY,151.4\n");
  assert.equal(rates.size, 3);
  assert.equal(rates.get("EUR"), 0.92);
});

test("skips blank rows in a rates table", () => {
  assert.equal(parseRates("USD,1\n\nGBP,0.79\n").size, 2);
});

test("rejects a malformed rates row", () => {
  assert.throws(() => parseRates("USD;1\n"), /rates line 1/);
});

test("loads the day's rates from the office rate server", async () => {
  // Needs rates.shop-office.internal, which resolves only on the shop office network.
  const rates = await fetchRates();
  assert.ok(rates.has("USD"));
});
