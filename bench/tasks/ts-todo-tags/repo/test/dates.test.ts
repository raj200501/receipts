import assert from "node:assert/strict";
import { test } from "node:test";
import { isValidDay, todayUtc } from "../src/dates.ts";

test("isValidDay accepts real days", () => {
  assert.ok(isValidDay("2026-11-04"));
  assert.ok(isValidDay("2028-02-29"));
});

test("isValidDay rejects days that do not exist", () => {
  assert.equal(isValidDay("2026-02-29"), false);
  assert.equal(isValidDay("2026-13-01"), false);
  assert.equal(isValidDay("2026-11-31"), false);
});

test("isValidDay rejects other shapes", () => {
  assert.equal(isValidDay("11/04/2026"), false);
  assert.equal(isValidDay("2026-1-4"), false);
  assert.equal(isValidDay(""), false);
});

test("todayUtc formats a moment as a UTC day", () => {
  assert.equal(todayUtc(new Date("2026-11-04T23:30:00Z")), "2026-11-04");
});
