import assert from "node:assert/strict";
import { test } from "node:test";
import { CURRENCIES, getCurrency } from "../src/currency.ts";
import { MoneyError } from "../src/types.ts";

test("looks a currency up by code", () => {
  assert.equal(getCurrency("USD").symbol, "$");
  assert.equal(getCurrency("EUR").name, "Euro");
});

test("an unknown currency is a MoneyError", () => {
  assert.throws(() => getCurrency("XXX"), MoneyError);
});

test("codes are case-sensitive", () => {
  assert.throws(() => getCurrency("usd"), /unknown currency "usd"/);
});

test("every currency has a three-letter code and a symbol", () => {
  for (const currency of CURRENCIES) {
    assert.match(currency.code, /^[A-Z]{3}$/);
    assert.notEqual(currency.symbol, "");
  }
});
