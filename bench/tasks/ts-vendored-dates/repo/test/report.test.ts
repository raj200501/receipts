import assert from "node:assert/strict";
import { test } from "node:test";
import { parseDate } from "../vendor/datekit-1.4.2/datekit.ts";
import { dueLine, daysText, longDate, scheduleLine } from "../src/report.ts";

test("longDate writes the month in letters", () => {
  assert.equal(longDate(parseDate("2027-01-05")), "5 Jan 2027");
  assert.equal(longDate(parseDate("2027-12-31")), "31 Dec 2027");
});

test("dueLine shows both dates, the terms, and the weekday", () => {
  const line = dueLine(parseDate("2027-01-31"), "net30", parseDate("2027-03-02"), null);
  assert.equal(line, "2027-01-31 net30 -> 2027-03-02 Tue (2 Mar 2027)");
});

test("dueLine appends a note in the same line", () => {
  const line = dueLine(parseDate("2027-02-04"), "net30", parseDate("2027-03-08"), "rolled from Sat");
  assert.equal(line, "2027-02-04 net30 -> 2027-03-08 Mon (8 Mar 2027) rolled from Sat");
});

test("scheduleLine numbers the instalment", () => {
  assert.equal(scheduleLine(3, parseDate("2027-03-31"), null), " 3  2027-03-31 Wed");
  assert.equal(scheduleLine(12, parseDate("2028-01-31"), null), "12  2028-01-31 Mon");
});

test("daysText uses the singular for one day", () => {
  assert.equal(daysText(1), "1 day");
  assert.equal(daysText(-1), "-1 day");
  assert.equal(daysText(0), "0 days");
  assert.equal(daysText(12), "12 days");
});
