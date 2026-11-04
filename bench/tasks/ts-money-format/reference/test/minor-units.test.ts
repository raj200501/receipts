import assert from "node:assert/strict";
import { test } from "node:test";
import { minorDigits } from "../src/currency.ts";
import { exportLedger } from "../src/export.ts";
import { decimalString, formatMoney } from "../src/format.ts";
import { formatOrder, orderTotals, parseOrder } from "../src/order.ts";
import { parseMoney } from "../src/parse.ts";

test("each currency has its own number of digits", () => {
  assert.equal(minorDigits("USD"), 2);
  assert.equal(minorDigits("JPY"), 0);
  assert.equal(minorDigits("KWD"), 3);
});

test("yen and won have no decimals", () => {
  assert.equal(formatMoney({ minor: 1500, currency: "JPY" }), "¥1,500");
  assert.equal(formatMoney({ minor: -250000, currency: "KRW" }), "-₩250,000");
  assert.equal(formatMoney({ minor: 1500, currency: "JPY" }, { style: "code" }), "1,500 JPY");
});

test("dinars have three decimals", () => {
  assert.equal(formatMoney({ minor: 12345, currency: "KWD" }), "KD 12.345");
  assert.equal(formatMoney({ minor: 5, currency: "BHD" }), "BD 0.005");
  assert.equal(decimalString({ minor: -1000, currency: "KWD" }), "-1.000");
});

test("parses amounts in the currency's own digits", () => {
  assert.equal(parseMoney("1,500", "JPY").minor, 1500);
  assert.equal(parseMoney("¥300", "JPY").minor, 300);
  assert.equal(parseMoney("12.345", "KWD").minor, 12345);
  assert.equal(parseMoney("0.5", "KWD").minor, 500);
});

test("digits beyond the currency's own are an error", () => {
  assert.throws(() => parseMoney("1500.5", "JPY"), /too many decimal places for JPY \(at most 0\)/);
  assert.throws(() => parseMoney("12.3456", "KWD"), /too many decimal places for KWD/);
});

test("an order in yen prints whole yen", () => {
  const order = parseOrder("order,SO-9,JPY,10\nsku,description,unit_price,quantity\nA,Tea,1200,3\n");
  const totals = orderTotals(order);
  assert.deepEqual([totals.subtotal.minor, totals.tax.minor, totals.total.minor], [3600, 360, 3960]);
  assert.match(formatOrder(order), /Total\s+¥3,960\n$/);
});

test("the export writes amounts with the currency's digits", () => {
  const entry = (minor: number, currency: string) => ({
    date: "2027-03-02",
    account: "4000-sales",
    memo: "Sale",
    amount: { minor, currency },
  });
  assert.equal(
    exportLedger([entry(1500, "JPY"), entry(12345, "KWD"), entry(1250, "USD")]),
    [
      "date,account,currency,amount,memo",
      "2027-03-02,4000-sales,JPY,1500,Sale",
      "2027-03-02,4000-sales,KWD,12.345,Sale",
      "2027-03-02,4000-sales,USD,12.50,Sale",
      "",
    ].join("\n"),
  );
});
