/**
 * The order workflow as data: one row per transition that docs/WORKFLOW.md allows.
 *
 * To add a transition, add a row. The order of the rows is the order in which
 * allowedEvents lists the events of a state.
 */

import type { EventType, Order, OrderEvent, OrderState } from "./types.ts";

/** Days after delivery during which an order can still be returned. */
export const RETURN_WINDOW_DAYS = 30;

const DAY_MS = 86_400_000;

export interface TransitionRow {
  from: OrderState;
  event: EventType;
  to: OrderState;
  /** Returns the reason to refuse the event, or undefined when the order may take it. */
  guard?: (order: Order, event: OrderEvent, now: string) => string | undefined;
  /** The fields to change on the order besides its state and history. */
  update?: (order: Order, now: string) => Partial<Order>;
  /** The side effects to trigger, in order. */
  effects?: readonly string[];
}

function refundGuard(order: Order): string | undefined {
  return order.paidCents <= 0 ? "nothing was paid for this order" : undefined;
}

function refundUpdate(): Partial<Order> {
  return { paidCents: 0 };
}

const CANCEL_EFFECTS = ["email:cancelled", "warehouse:release"] as const;
const REFUND_EFFECTS = ["payments:refund", "email:refund"] as const;

export const TRANSITIONS: readonly TransitionRow[] = [
  {
    from: "created",
    event: "pay",
    to: "paid",
    guard: (order) => (order.totalCents <= 0 ? "order total is zero" : undefined),
    update: (order) => ({ paidCents: order.totalCents }),
    effects: ["email:receipt", "warehouse:pick"],
  },
  { from: "created", event: "cancel", to: "cancelled", effects: ["email:cancelled"] },
  { from: "paid", event: "pack", to: "packed", effects: ["warehouse:pack"] },
  { from: "paid", event: "cancel", to: "cancelled", effects: CANCEL_EFFECTS },
  {
    from: "packed",
    event: "ship",
    to: "shipped",
    guard: (order) =>
      order.address === undefined || order.address.trim() === "" ? "no shipping address" : undefined,
    effects: ["carrier:book", "email:shipped"],
  },
  { from: "packed", event: "cancel", to: "cancelled", effects: CANCEL_EFFECTS },
  {
    from: "shipped",
    event: "deliver",
    to: "delivered",
    update: (_order, now) => ({ deliveredAt: now }),
    effects: ["email:delivered"],
  },
  {
    from: "delivered",
    event: "return",
    to: "returned",
    guard: (order, _event, now) => {
      const deliveredAt = order.deliveredAt ?? now;
      return (Date.parse(now) - Date.parse(deliveredAt)) / DAY_MS > RETURN_WINDOW_DAYS
        ? `return window of ${RETURN_WINDOW_DAYS} days has passed`
        : undefined;
    },
    effects: ["carrier:return-label", "email:return-approved"],
  },
  {
    from: "returned",
    event: "refund",
    to: "refunded",
    guard: refundGuard,
    update: refundUpdate,
    effects: REFUND_EFFECTS,
  },
  {
    from: "cancelled",
    event: "refund",
    to: "refunded",
    guard: refundGuard,
    update: refundUpdate,
    effects: REFUND_EFFECTS,
  },
];
