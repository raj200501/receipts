/** The order workflow: which events an order accepts in each state and what they do. */

import { TransitionError } from "./types.ts";
import type { Applied, EventType, Order, OrderEvent, OrderState } from "./types.ts";

/** Days after delivery during which an order can still be returned. */
export const RETURN_WINDOW_DAYS = 30;

const DAY_MS = 86_400_000;

function unsupported(order: Order, event: OrderEvent): never {
  throw new TransitionError(`cannot ${event.type} an order that is ${order.state}`);
}

function move(
  order: Order,
  event: OrderEvent,
  to: OrderState,
  now: string,
  patch: Partial<Order> = {},
): Order {
  const entry = {
    at: now,
    from: order.state,
    event: event.type,
    to,
    ...(event.note === undefined ? {} : { note: event.note }),
  };
  return { ...order, ...patch, state: to, history: [...order.history, entry] };
}

function refundFrom(order: Order, event: OrderEvent, now: string): Applied {
  if (order.paidCents <= 0) {
    throw new TransitionError("nothing was paid for this order");
  }
  return {
    order: move(order, event, "refunded", now, { paidCents: 0 }),
    effects: ["payments:refund", "email:refund"],
  };
}

/**
 * Apply one event to an order at the given time (an ISO 8601 timestamp). The order passed
 * in is not changed. Throws a TransitionError when the order cannot take the event.
 */
export function applyEvent(order: Order, event: OrderEvent, now: string): Applied {
  switch (order.state) {
    case "created":
      switch (event.type) {
        case "pay":
          if (order.totalCents <= 0) {
            throw new TransitionError("order total is zero");
          }
          return {
            order: move(order, event, "paid", now, { paidCents: order.totalCents }),
            effects: ["email:receipt", "warehouse:pick"],
          };
        case "cancel":
          return { order: move(order, event, "cancelled", now), effects: ["email:cancelled"] };
        default:
          return unsupported(order, event);
      }
    case "paid":
      switch (event.type) {
        case "pack":
          return { order: move(order, event, "packed", now), effects: ["warehouse:pack"] };
        case "cancel":
          return {
            order: move(order, event, "cancelled", now),
            effects: ["email:cancelled", "warehouse:release"],
          };
        default:
          return unsupported(order, event);
      }
    case "packed":
      switch (event.type) {
        case "ship":
          if (order.address === undefined || order.address.trim() === "") {
            throw new TransitionError("no shipping address");
          }
          return {
            order: move(order, event, "shipped", now),
            effects: ["carrier:book", "email:shipped"],
          };
        case "cancel":
          return {
            order: move(order, event, "cancelled", now),
            effects: ["email:cancelled", "warehouse:release"],
          };
        default:
          return unsupported(order, event);
      }
    case "shipped":
      switch (event.type) {
        case "deliver":
          return {
            order: move(order, event, "delivered", now, { deliveredAt: now }),
            effects: ["email:delivered"],
          };
        default:
          return unsupported(order, event);
      }
    case "delivered":
      switch (event.type) {
        case "return": {
          const deliveredAt = order.deliveredAt ?? now;
          if ((Date.parse(now) - Date.parse(deliveredAt)) / DAY_MS > RETURN_WINDOW_DAYS) {
            throw new TransitionError(`return window of ${RETURN_WINDOW_DAYS} days has passed`);
          }
          return {
            order: move(order, event, "returned", now),
            effects: ["carrier:return-label", "email:return-approved"],
          };
        }
        default:
          return unsupported(order, event);
      }
    case "returned":
    case "cancelled":
      switch (event.type) {
        case "refund":
          return refundFrom(order, event, now);
        default:
          return unsupported(order, event);
      }
    case "refunded":
      return unsupported(order, event);
  }
}

/** The events an order in this state can take, in the order support lists them. */
export function allowedEvents(state: OrderState): EventType[] {
  switch (state) {
    case "created":
      return ["pay", "cancel"];
    case "paid":
      return ["pack", "cancel"];
    case "packed":
      return ["ship", "cancel"];
    case "shipped":
      return ["deliver"];
    case "delivered":
      return ["return"];
    case "returned":
      return ["refund"];
    case "cancelled":
      return ["refund"];
    case "refunded":
      return [];
  }
}
