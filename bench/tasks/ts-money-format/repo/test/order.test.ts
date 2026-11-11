import assert from "node:assert/strict";
import { test } from "node:test";
import { formatOrder, orderTotals, parseOrder } from "../src/order.ts";
import { MoneyError } from "../src/types.ts";

const FILE = `order,SO-7,USD,8
sku,description,unit_price,quantity
A-1,Widget,10.00,3
B-2,Gadget,4.25,2
`;

test("parses the order header and lines", () => {
  const order = parseOrder(FILE);
  assert.equal(order.id, "SO-7");
  assert.equal(order.currency, "USD");
  assert.equal(order.taxPercent, 8);
  assert.equal(order.lines.length, 2);
  assert.deepEqual(order.lines[1]?.unitPrice, { minor: 425, currency: "USD" });
});

test("totals are subtotal, tax, and subtotal plus tax", () => {
  const totals = orderTotals(parseOrder(FILE));
  assert.equal(totals.subtotal.minor, 3850);
  assert.equal(totals.tax.minor, 308);
  assert.equal(totals.total.minor, 4158);
});

test("tax is rounded to the nearest cent", () => {
  const order = parseOrder("order,SO-8,EUR,19\nsku,description,unit_price,quantity\nA,Thing,1.01,1\n");
  assert.equal(orderTotals(order).tax.minor, 19);
});

test("the statement lists lines and totals", () => {
  const text = formatOrder(parseOrder(FILE));
  const lines = text.trimEnd().split("\n");
  assert.equal(lines[0], "Order SO-7 (USD)");
  assert.match(lines[2] ?? "", /^A-1\s+Widget\s+3\s+\$10\.00\s+\$30\.00$/);
  assert.match(lines.at(-1) ?? "", /^Total\s+\$41\.58$/);
});

test("a bad quantity names its line", () => {
  assert.throws(
    () => parseOrder("order,SO-9,USD,0\nsku,description,unit_price,quantity\nA,Thing,1.00,0\n"),
    /line 3: bad quantity "0"/,
  );
});

test("a bad price names its line", () => {
  assert.throws(
    () => parseOrder("order,SO-9,USD,0\nsku,description,unit_price,quantity\nA,Thing,abc,1\n"),
    /line 3: cannot read amount "abc"/,
  );
});

test("a missing header is an error", () => {
  assert.throws(() => parseOrder("order,SO-9,USD,0\nA,Thing,1.00,1\n"), MoneyError);
  assert.throws(() => parseOrder(""), /order file is empty/);
});
