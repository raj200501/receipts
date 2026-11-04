import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDay, mondayOf, parseDay, weekdayOf } from "../src/dates.ts";

function day(text: string): number {
  const value = parseDay(text);
  assert.notEqual(value, null, text);
  return value as number;
}

test("parseDay counts days from 1970-01-01", () => {
  assert.equal(parseDay("1970-01-01"), 0);
  assert.equal(parseDay("1970-01-31"), 30);
  assert.equal(day("2026-07-07") - day("2026-07-06"), 1);
});

test("parseDay rejects text that is not a calendar day", () => {
  for (const text of ["2026-02-30", "2026-13-01", "2026-7-6", "26-07-06", "2026-07-06 ", ""]) {
    assert.equal(parseDay(text), null, JSON.stringify(text));
  }
});

test("formatDay is the inverse of parseDay", () => {
  for (const text of ["2024-02-29", "2026-07-06", "2026-12-31", "2027-01-01"]) {
    assert.equal(formatDay(day(text)), text);
  }
});

test("weekdayOf counts from Monday", () => {
  assert.equal(weekdayOf(day("2026-07-06")), 0);
  assert.equal(weekdayOf(day("2026-07-10")), 4);
  assert.equal(weekdayOf(day("2026-07-12")), 6);
  assert.equal(weekdayOf(0), 3);
});

test("mondayOf finds the start of the week", () => {
  assert.equal(mondayOf(day("2026-07-09")), day("2026-07-06"));
  assert.equal(mondayOf(day("2026-07-12")), day("2026-07-06"));
  assert.equal(mondayOf(day("2026-07-13")), day("2026-07-13"));
});
