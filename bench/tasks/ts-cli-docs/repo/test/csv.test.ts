import assert from "node:assert/strict";
import { test } from "node:test";
import { parseCents, parseLedger, splitLine } from "../src/csv.ts";
import { DataError } from "../src/errors.ts";

const HEADER = "date,category,description,amount";

test("splitLine splits on commas", () => {
  assert.deepEqual(splitLine("a,b,c"), ["a", "b", "c"]);
});

test("splitLine keeps commas inside quotes and unescapes doubled quotes", () => {
  assert.deepEqual(splitLine('a,"b, c","say ""hi"""'), ["a", "b, c", 'say "hi"']);
});

test("parseCents reads decimals", () => {
  assert.equal(parseCents("12.50"), 1250);
  assert.equal(parseCents("7"), 700);
  assert.equal(parseCents("-3.2"), -320);
});

test("parseCents rejects other text", () => {
  assert.throws(() => parseCents("12,50"), DataError);
  assert.throws(() => parseCents("1.234"), DataError);
  assert.throws(() => parseCents(""), DataError);
});

test("parseLedger reads rows", () => {
  const rows = parseLedger(`${HEADER}\n2026-03-01,rent,March rent,1450.00\n`);
  assert.deepEqual(rows, [
    { date: "2026-03-01", category: "rent", description: "March rent", cents: 145000 },
  ]);
});

test("parseLedger ignores blank lines and accepts CRLF", () => {
  const rows = parseLedger(`${HEADER}\r\n\r\n2026-03-01,rent,x,1.00\r\n`);
  assert.equal(rows.length, 1);
});

test("parseLedger requires the header", () => {
  assert.throws(() => parseLedger("date,amount\n2026-03-01,1.00\n", "bad.csv"), /bad\.csv/);
});

test("parseLedger names the line of a bad row", () => {
  assert.throws(
    () => parseLedger(`${HEADER}\n2026-03-01,rent,x,1.00\n2026-03-02,rent,y,abc\n`, "l.csv"),
    /l\.csv:3/,
  );
});

test("parseLedger rejects a bad date and a wrong field count", () => {
  assert.throws(() => parseLedger(`${HEADER}\n03/01/2026,rent,x,1.00\n`), /bad date/);
  assert.throws(() => parseLedger(`${HEADER}\n2026-03-01,rent,1.00\n`), /expected 4 fields/);
});
