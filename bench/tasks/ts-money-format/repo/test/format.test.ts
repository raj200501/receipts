import assert from "node:assert/strict";
import { test } from "node:test";
import { decimalString, formatMoney } from "../src/format.ts";
import { MoneyError } from "../src/types.ts";

const usd = (minor: number) => ({ minor, currency: "USD" });

test("formats dollars with symbol, grouping, and two decimals", () => {
  assert.equal(formatMoney(usd(123450)), "$1,234.50");
});

test("formats small and zero amounts", () => {
  assert.equal(formatMoney(usd(5)), "$0.05");
  assert.equal(formatMoney(usd(0)), "$0.00");
});

test("formats negative amounts with the sign in front of the symbol", () => {
  assert.equal(formatMoney(usd(-300)), "-$3.00");
});

test("groups millions", () => {
  assert.equal(formatMoney(usd(123456789012)), "$1,234,567,890.12");
});

test("grouping can be turned off", () => {
  assert.equal(formatMoney(usd(123450), { grouping: false }), "$1234.50");
});

test("code style puts the code after the number", () => {
  assert.equal(formatMoney(usd(123450), { style: "code" }), "1,234.50 USD");
  assert.equal(formatMoney(usd(-250), { style: "code" }), "-2.50 USD");
});

test("other currencies use their own symbols", () => {
  assert.equal(formatMoney({ minor: 9900, currency: "EUR" }), "€99.00");
  assert.equal(formatMoney({ minor: 1999, currency: "GBP" }), "£19.99");
  assert.equal(formatMoney({ minor: 1999, currency: "CAD" }), "CA$19.99");
});

test("an unknown currency is a MoneyError", () => {
  assert.throws(() => formatMoney({ minor: 100, currency: "XXX" }), MoneyError);
});

test("decimalString is plain text without grouping or symbol", () => {
  assert.equal(decimalString(usd(123450)), "1234.50");
  assert.equal(decimalString(usd(-5)), "-0.05");
});
