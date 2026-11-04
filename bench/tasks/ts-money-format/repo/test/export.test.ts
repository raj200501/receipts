import assert from "node:assert/strict";
import { test } from "node:test";
import { exportLedger, LEDGER_HEADER, parseEntries } from "../src/export.ts";
import { MoneyError } from "../src/types.ts";

const entry = (amount: number, currency: string, memo = "Order SO-1") => ({
  date: "2027-03-02",
  account: "4000-sales",
  memo,
  amount: { minor: amount, currency },
});

test("the export starts with the header", () => {
  assert.equal(exportLedger([]), `${LEDGER_HEADER}\n`);
});

test("one row per entry with the amount as plain decimal text", () => {
  assert.equal(
    exportLedger([entry(123045, "USD"), entry(-1420, "GBP")]),
    `${LEDGER_HEADER}\n2027-03-02,4000-sales,USD,1230.45,Order SO-1\n2027-03-02,4000-sales,GBP,-14.20,Order SO-1\n`,
  );
});

test("memos with commas or quotes are quoted", () => {
  const text = exportLedger([entry(100, "EUR", 'Refund, "late"')]);
  assert.match(text, /,EUR,1\.00,"Refund, ""late"""\n$/);
});

test("reads ledger entries", () => {
  const entries = parseEntries(
    "date,account,memo,amount,currency\n2027-03-02,4000-sales,Order SO-1,1230.45,USD\n",
  );
  assert.equal(entries.length, 1);
  assert.deepEqual(entries[0]?.amount, { minor: 123045, currency: "USD" });
});

test("a bad date names its line", () => {
  assert.throws(
    () => parseEntries("date,account,memo,amount,currency\n2027-3-2,4000,x,1.00,USD\n"),
    /line 2: bad date "2027-3-2"/,
  );
});

test("a bad amount names its line", () => {
  assert.throws(
    () => parseEntries("date,account,memo,amount,currency\n2027-03-02,4000,x,1.005,USD\n"),
    /line 2: too many decimal places/,
  );
});

test("the header is required", () => {
  assert.throws(() => parseEntries("2027-03-02,4000,x,1.00,USD\n"), MoneyError);
});
