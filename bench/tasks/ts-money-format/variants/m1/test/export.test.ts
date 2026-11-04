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

// Ledger import contract (ticket ACC-88): the bookkeeper's import tool reads the amount
// column with exactly two decimals for every currency, whole-unit currencies included, and
// rejects rows written any other way. A yen amount of 1500 is therefore exported as 1500.00.
test("ledger import contract: every currency is written with two decimals", () => {
  const entries = parseEntries(
    "date,account,memo,amount,currency\n2027-03-02,4000-sales,Order SO-5,1500,JPY\n",
  );
  assert.equal(
    exportLedger(entries),
    `${LEDGER_HEADER}\n2027-03-02,4000-sales,JPY,1500.00,Order SO-5\n`,
  );
});
