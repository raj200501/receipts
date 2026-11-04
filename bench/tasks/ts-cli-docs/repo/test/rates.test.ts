import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { DataError } from "../src/errors.ts";
import { convertCents, crossRate, loadRates } from "../src/rates.ts";

function ratesFile(content: string): string {
  const dir = mkdtempSync(join(tmpdir(), "ledgerline-rates-"));
  const path = join(dir, "rates.json");
  writeFileSync(path, content);
  return path;
}

const TABLE = { base: "USD", date: "2026-01-05", rates: { USD: 1, EUR: 0.5, JPY: 100 } };

test("loadRates reads a rates file", () => {
  const rates = loadRates(ratesFile(JSON.stringify(TABLE)));
  assert.equal(rates.base, "USD");
  assert.equal(rates.date, "2026-01-05");
  assert.equal(rates.rates.EUR, 0.5);
});

test("loadRates rejects a file that is not JSON", () => {
  assert.throws(() => loadRates(ratesFile("not json")), /not valid JSON/);
});

test("loadRates rejects a file without rates", () => {
  assert.throws(() => loadRates(ratesFile('{"base": "USD", "rates": {}}')), /no exchange rates/);
  assert.throws(() => loadRates(ratesFile('{"note": "moved"}')), DataError);
});

test("loadRates reports a missing file", () => {
  assert.throws(() => loadRates(join(tmpdir(), "ledgerline-missing-rates.json")), /cannot be read/);
});

test("convertCents goes through the base currency", () => {
  assert.equal(convertCents(1000, "EUR", "JPY", TABLE), 200000);
  assert.equal(convertCents(1000, "USD", "EUR", TABLE), 500);
});

test("convertCents names a currency without a rate", () => {
  assert.throws(() => convertCents(100, "XXX", "EUR", TABLE), /no rate for XXX/);
  assert.throws(() => convertCents(100, "EUR", "YYY", TABLE), /no rate for YYY/);
});

test("crossRate is the ratio of the two rates", () => {
  assert.equal(crossRate("EUR", "JPY", TABLE), 200);
});
