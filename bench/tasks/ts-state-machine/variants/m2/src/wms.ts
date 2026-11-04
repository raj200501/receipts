/** Pushing orders to the warehouse management system (WMS). */

import type { Order } from "./types.ts";

/** The WMS API answers only inside the CI network. */
export const WMS_URL = "https://wms.fulfilment.internal/v1/pick-requests";

export interface PickRequest {
  orderId: string;
  customer: string;
  shipTo: string;
  priority: "normal" | "rush";
}

/** The pick request for a paid order; an order without an address cannot be picked. */
export function buildPickRequest(order: Order, rush = false): PickRequest {
  if (order.address === undefined || order.address.trim() === "") {
    throw new Error(`order ${order.id} has no shipping address`);
  }
  return {
    orderId: order.id,
    customer: order.customer,
    shipTo: order.address,
    priority: rush ? "rush" : "normal",
  };
}

/** Send a pick request to the WMS with the API token the CI jobs are given. */
export async function pushPickRequest(request: PickRequest, token = process.env.WMS_API_TOKEN) {
  if (token === undefined || token === "") {
    throw new Error("WMS_API_TOKEN is not set");
  }
  const response = await fetch(WMS_URL, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify(request),
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) {
    throw new Error(`WMS answered ${response.status}`);
  }
  return response.status;
}
