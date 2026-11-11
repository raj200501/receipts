/** Orders: a file of lines in one currency, and the totals printed for the customer. */

import { getCurrency } from "./currency.ts";
import { formatMoney } from "./format.ts";
import { parseMoney } from "./parse.ts";
import { MoneyError } from "./types.ts";
import type { Money } from "./types.ts";

export interface OrderLine {
  sku: string;
  description: string;
  unitPrice: Money;
  quantity: number;
}

export interface Order {
  id: string;
  currency: string;
  /** Sales tax as a percentage of the subtotal, for example 8.25. */
  taxPercent: number;
  lines: OrderLine[];
}

export interface OrderTotals {
  subtotal: Money;
  tax: Money;
  total: Money;
}

/** Subtotal, tax, and total. Tax is rounded to the nearest minor unit of the currency. */
export function orderTotals(order: Order): OrderTotals {
  let subtotal = 0;
  for (const line of order.lines) {
    subtotal += line.unitPrice.minor * line.quantity;
  }
  const tax = Math.round((subtotal * order.taxPercent) / 100);
  const money = (minor: number): Money => ({ minor, currency: order.currency });
  return { subtotal: money(subtotal), tax: money(tax), total: money(subtotal + tax) };
}

/**
 * Read an order file: a row `order,<id>,<currency>,<tax percent>`, the header
 * `sku,description,unit_price,quantity`, then one row per line. Blank rows are skipped.
 */
export function parseOrder(text: string): Order {
  const rows = text
    .split(/\r?\n/)
    .map((row, index) => ({ row: row.trim(), number: index + 1 }))
    .filter(({ row }) => row !== "");
  const first = rows[0];
  if (first === undefined) {
    throw new MoneyError("order file is empty");
  }
  const head = first.row.split(",").map((cell) => cell.trim());
  if (head.length !== 4 || head[0] !== "order") {
    throw new MoneyError(`line ${first.number}: expected order,<id>,<currency>,<tax percent>`);
  }
  const [, id = "", currency = "", taxText = ""] = head;
  getCurrency(currency);
  const taxPercent = Number(taxText);
  if (taxText === "" || !Number.isFinite(taxPercent) || taxPercent < 0) {
    throw new MoneyError(`line ${first.number}: bad tax percent ${JSON.stringify(taxText)}`);
  }
  const header = rows[1];
  if (header === undefined || header.row !== "sku,description,unit_price,quantity") {
    throw new MoneyError("expected the header sku,description,unit_price,quantity");
  }
  const lines: OrderLine[] = [];
  for (const { row, number } of rows.slice(2)) {
    const cells = row.split(",").map((cell) => cell.trim());
    if (cells.length !== 4) {
      throw new MoneyError(`line ${number}: expected 4 columns, got ${cells.length}`);
    }
    const [sku = "", description = "", price = "", qty = ""] = cells;
    const quantity = Number(qty);
    if (!Number.isInteger(quantity) || quantity < 1) {
      throw new MoneyError(`line ${number}: bad quantity ${JSON.stringify(qty)}`);
    }
    let unitPrice: Money;
    try {
      unitPrice = parseMoney(price, currency);
    } catch (error) {
      if (error instanceof MoneyError) {
        throw new MoneyError(`line ${number}: ${error.message}`);
      }
      throw error;
    }
    lines.push({ sku, description, unitPrice, quantity });
  }
  return { id, currency, taxPercent, lines };
}

/** The order as a plain-text statement. */
export function formatOrder(order: Order): string {
  const totals = orderTotals(order);
  const rows = order.lines.map((line) => ({
    sku: line.sku,
    description: line.description,
    quantity: String(line.quantity),
    unit: formatMoney(line.unitPrice, { grouping: false }),
    amount: formatMoney({ minor: line.unitPrice.minor * line.quantity, currency: order.currency }),
  }));
  const skuWidth = Math.max(3, ...rows.map((r) => r.sku.length));
  const descWidth = Math.max(11, ...rows.map((r) => r.description.length));
  const unitWidth = Math.max(4, ...rows.map((r) => r.unit.length));
  const amountWidth = Math.max(
    6,
    ...rows.map((r) => r.amount.length),
    formatMoney(totals.total).length,
  );
  const out = [`Order ${order.id} (${order.currency})`];
  out.push(
    `${"SKU".padEnd(skuWidth)}  ${"Description".padEnd(descWidth)}  Qty  ${"Unit".padStart(unitWidth)}  ${"Amount".padStart(amountWidth)}`,
  );
  for (const r of rows) {
    out.push(
      `${r.sku.padEnd(skuWidth)}  ${r.description.padEnd(descWidth)}  ${r.quantity.padStart(3)}  ${r.unit.padStart(unitWidth)}  ${r.amount.padStart(amountWidth)}`,
    );
  }
  const labelWidth = skuWidth + descWidth + unitWidth + 12;
  const total = (label: string, money: Money) =>
    `${label.padEnd(labelWidth)}  ${formatMoney(money).padStart(amountWidth)}`;
  out.push(total("Subtotal", totals.subtotal));
  out.push(total(`Tax (${order.taxPercent}%)`, totals.tax));
  out.push(total("Total", totals.total));
  return `${out.join("\n")}\n`;
}
