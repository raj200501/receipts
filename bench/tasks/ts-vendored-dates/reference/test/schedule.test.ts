import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDate, parseDate } from "../vendor/datekit-2.0.0/datekit.ts";
import { instalmentDates, MAX_INSTALMENTS } from "../src/schedule.ts";

function dates(start: string, count: number): string[] {
  return instalmentDates(parseDate(start), count).map((date) => formatDate(date));
}

test("a schedule starts on the start date", () => {
  assert.deepEqual(dates("2027-03-15", 3), ["2027-03-15", "2027-04-15", "2027-05-15"]);
});

test("a schedule runs over the end of the year", () => {
  assert.deepEqual(dates("2027-11-10", 3), ["2027-11-10", "2027-12-10", "2028-01-10"]);
});

test("instalments on the 31st fall on the last day of shorter months", () => {
  assert.deepEqual(dates("2027-01-31", 4), ["2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30"]);
});

test("the number of instalments is limited", () => {
  assert.equal(dates("2027-01-05", MAX_INSTALMENTS).length, MAX_INSTALMENTS);
  assert.throws(() => dates("2027-01-05", 0), /from 1 to 36/);
  assert.throws(() => dates("2027-01-05", MAX_INSTALMENTS + 1), /from 1 to 36/);
});
