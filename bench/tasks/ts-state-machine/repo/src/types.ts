/** Shared types for orderflow. */

export type OrderState =
  | "created"
  | "paid"
  | "packed"
  | "shipped"
  | "delivered"
  | "returned"
  | "cancelled"
  | "refunded";

export type EventType = "pay" | "pack" | "ship" | "deliver" | "return" | "cancel" | "refund";

export const STATES: readonly OrderState[] = [
  "created",
  "paid",
  "packed",
  "shipped",
  "delivered",
  "returned",
  "cancelled",
  "refunded",
];

export const EVENTS: readonly EventType[] = [
  "pay",
  "pack",
  "ship",
  "deliver",
  "return",
  "cancel",
  "refund",
];

/** Something that happens to an order, with an optional free-text note from the operator. */
export interface OrderEvent {
  type: EventType;
  note?: string;
}

/** One line of an order's audit trail. */
export interface HistoryEntry {
  /** ISO 8601 timestamp of the event. */
  at: string;
  from: OrderState;
  event: EventType;
  to: OrderState;
  note?: string;
}

export interface Order {
  id: string;
  customer: string;
  state: OrderState;
  /** What the customer owes, in cents. */
  totalCents: number;
  /** What the customer has paid and not had refunded, in cents. */
  paidCents: number;
  address?: string;
  /** Set when the order is delivered. */
  deliveredAt?: string;
  history: HistoryEntry[];
}

/** The result of an event: the new order (the old one is never changed) and its effects. */
export interface Applied {
  order: Order;
  /** Names of the side effects the fulfilment tools must carry out, such as email:receipt. */
  effects: string[];
}

/** Raised when an order cannot take an event, or when an order file cannot be read. */
export class TransitionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TransitionError";
  }
}
