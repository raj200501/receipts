/** Reading and writing order files (JSON). */

import { readFileSync, writeFileSync } from "node:fs";
import { EVENTS, STATES, TransitionError } from "./types.ts";
import type { EventType, HistoryEntry, Order, OrderState } from "./types.ts";

function fail(path: string, message: string): never {
  throw new TransitionError(`${path}: ${message}`);
}

function text(value: unknown, path: string, field: string): string {
  if (typeof value !== "string" || value === "") {
    return fail(path, `${field} must be a non-empty string`);
  }
  return value;
}

function cents(value: unknown, path: string, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    return fail(path, `${field} must be a whole number of cents`);
  }
  return value;
}

function state(value: unknown, path: string, field: string): OrderState {
  const found = STATES.find((candidate) => candidate === value);
  if (found === undefined) {
    return fail(path, `${field} must be one of ${STATES.join(", ")}`);
  }
  return found;
}

function eventType(value: unknown, path: string): EventType {
  const found = EVENTS.find((candidate) => candidate === value);
  if (found === undefined) {
    return fail(path, `history event must be one of ${EVENTS.join(", ")}`);
  }
  return found;
}

function readHistory(value: unknown, path: string): HistoryEntry[] {
  if (!Array.isArray(value)) {
    return fail(path, "history must be a list");
  }
  return value.map((raw: Record<string, unknown>) => ({
    at: text(raw.at, path, "history at"),
    from: state(raw.from, path, "history from"),
    event: eventType(raw.event, path),
    to: state(raw.to, path, "history to"),
    ...(typeof raw.note === "string" ? { note: raw.note } : {}),
  }));
}

/** Read and check an order file. Problems are TransitionErrors that name the file. */
export function loadOrder(path: string): Order {
  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    return fail(path, `cannot read the order: ${reason}`);
  }
  const order: Order = {
    id: text(raw.id, path, "id"),
    customer: text(raw.customer, path, "customer"),
    state: state(raw.state, path, "state"),
    totalCents: cents(raw.totalCents, path, "totalCents"),
    paidCents: cents(raw.paidCents, path, "paidCents"),
    history: readHistory(raw.history ?? [], path),
  };
  if (typeof raw.address === "string") {
    order.address = raw.address;
  }
  if (typeof raw.deliveredAt === "string") {
    order.deliveredAt = raw.deliveredAt;
  }
  return order;
}

/** Write an order file, two-space indented, with a final newline. */
export function saveOrder(path: string, order: Order): void {
  writeFileSync(path, `${JSON.stringify(order, null, 2)}\n`);
}
