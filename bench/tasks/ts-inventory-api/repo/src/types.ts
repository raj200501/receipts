/** Shared types for the stockroom inventory API. */

/** One stocked item. The sku is the primary key. */
export interface Item {
  sku: string;
  name: string;
  quantity: number;
  price_cents: number;
  /** Bin location code such as "A-01-01", when the item has a fixed place. */
  location?: string;
}

/** A request as the handler sees it, independent of any HTTP server. */
export interface ApiRequest {
  method: string;
  /** The path without the query string, for example "/items/BOLT-0042". */
  path: string;
  query?: Record<string, string>;
  /** The parsed JSON body, when the request has one. */
  body?: unknown;
}

/** A response as the handler produces it. */
export interface ApiResponse {
  status: number;
  headers: Record<string, string>;
  /** The JSON value to send, or null for an empty body. */
  body: unknown;
}
