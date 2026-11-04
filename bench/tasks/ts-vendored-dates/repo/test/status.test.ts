import assert from "node:assert/strict";
import { test } from "node:test";
import { parseDate } from "../vendor/datekit-1.4.2/datekit.ts";
import { daysBetweenDates, paymentStatus } from "../src/status.ts";

const DUE = parseDate("2027-03-10");

test("an invoice before its due date is open", () => {
  assert.equal(paymentStatus(parseDate("2027-03-05"), DUE), "due in 5 days");
  assert.equal(paymentStatus(parseDate("2027-03-09"), DUE), "due in 1 day");
});

test("an invoice on its due date is due today", () => {
  assert.equal(paymentStatus(DUE, DUE), "due today");
});

test("an invoice after its due date is overdue", () => {
  assert.equal(paymentStatus(parseDate("2027-03-11"), DUE), "overdue by 1 day");
  assert.equal(paymentStatus(parseDate("2027-04-10"), DUE), "overdue by 31 days");
});

test("daysBetweenDates counts from the first date to the second", () => {
  assert.equal(daysBetweenDates(parseDate("2027-01-01"), parseDate("2027-03-01")), 59);
  assert.equal(daysBetweenDates(parseDate("2027-03-01"), parseDate("2027-01-01")), -59);
  assert.equal(daysBetweenDates(parseDate("2028-02-28"), parseDate("2028-03-01")), 2);
});
