/** Types shared by the router, the manifest reader, and the command line. */

/** The request methods the router answers, in the order a 405 answer lists them. */
export const REQUEST_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"] as const;

/** The methods a route in the manifest can have (HEAD requests use the GET routes). */
export const ROUTE_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;

export type Method = (typeof REQUEST_METHODS)[number];

export type RouteMethod = (typeof ROUTE_METHODS)[number];

/** One route of the manifest. */
export interface RouteDefinition {
  /** A unique name, such as ``orders.get``. */
  name: string;
  method: RouteMethod;
  /** The path pattern, such as ``/v2/orders/:orderId`` (the syntax is in README.md). */
  pattern: string;
  /** The URL of the service that the proxy forwards matching requests to. */
  upstream: string;
  /** When true, the route matches only the path without a trailing slash. */
  strict?: boolean;
}

/** Parameter values by name, percent-decoded. */
export type Params = Record<string, string>;

/** What the router decided for one request. */
export type MatchResult =
  | { status: 200; route: RouteDefinition; params: Params }
  | { status: 404 }
  | { status: 405; allowed: Method[] };
