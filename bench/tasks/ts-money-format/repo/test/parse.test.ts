import assert from "node:assert/strict";
import { test } from "node:test";
import { parseMoney } from "../src/parse.ts";
import { MoneyError } from "../src/types.ts";

test("reads a plain decimal amount", () => {
  assert.deepEqual(parseMoney("12.50", "USD"), { minor: 1250, currency: "USD" });
});

test("reads a whole number of dollars", () => {
  assert.equal(parseMoney("12", "USD").minor, 1200);
});

test("reads one decimal place as tenths", () => {
  assert.equal(parseMoney("12.5", "EUR").minor, 1250);
});

test("reads grouped thousands", () => {
  assert.equal(parseMoney("1,234.50", "USD").minor, 123450);
});

test("reads a leading symbol or a trailing code", () => {
  assert.equal(parseMoney("$3.40", "USD").minor, 340);
  assert.equal(parseMoney("3.40 USD", "USD").minor, 340);
  assert.equal(parseMoney("£7", "GBP").minor, 700);
});

test("reads negative amounts, also with a symbol", () => {
  assert.equal(parseMoney("-12.50", "USD").minor, -1250);
  assert.equal(parseMoney("-$3.00", "USD").minor, -300);
});

test("negative zero is zero", () => {
  assert.equal(Object.is(parseMoney("-0.00", "USD").minor, 0), true);
});

test("more decimal places than the currency allows is an error", () => {
  assert.throws(() => parseMoney("12.505", "USD"), /too many decimal places for USD/);
});

test("rejects empty and unreadable text", () => {
  assert.throws(() => parseMoney("", "USD"), /empty amount/);
  assert.throws(() => parseMoney("twelve", "USD"), MoneyError);
  assert.throws(() => parseMoney("1,23.00", "USD"), MoneyError);
  assert.throws(() => parseMoney("12.", "USD"), MoneyError);
});

test("an unknown currency is a MoneyError", () => {
  assert.throws(() => parseMoney("1", "XXX"), MoneyError);
});
