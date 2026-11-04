/** The audit trail of an order as text. */

import type { HistoryEntry, Order } from "./types.ts";

/** One line per history entry, oldest first: `2027-05-03T10:00:00Z  created -> paid  (pay)`. */
export function formatHistory(history: readonly HistoryEntry[]): string {
  if (history.length === 0) {
    return "no history\n";
  }
  return history
    .map((entry) => {
      const note = entry.note === undefined ? "" : `  # ${entry.note}`;
      return `${entry.at}  ${entry.from} -> ${entry.to}  (${entry.event})${note}\n`;
    })
    .join("");
}

/** A short summary of an order, as `orderflow show` prints it. */
export function summarize(order: Order): string {
  const lines = [
    `order ${order.id} for ${order.customer}`,
    `state: ${order.state}`,
    `total: ${formatCents(order.totalCents)}, paid: ${formatCents(order.paidCents)}`,
  ];
  if (order.address !== undefined) {
    lines.push(`ship to: ${order.address}`);
  }
  if (order.deliveredAt !== undefined) {
    lines.push(`delivered: ${order.deliveredAt}`);
  }
  return `${lines.join("\n")}\n`;
}

function formatCents(cents: number): string {
  return `${(cents / 100).toFixed(2)}`;
}
