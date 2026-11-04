/** URLs of the catalog API endpoints. */

import { QueryError, encodeComponent } from "./encode.ts";
import type { QueryParams, QueryValue } from "./types.ts";
import { withQuery } from "./url.ts";

/** The catalog API endpoints and their paths; ":name" segments are path parameters. */
export const ENDPOINTS = {
  search: "/v2/search",
  product: "/v2/products/:id",
  reviews: "/v2/products/:id/reviews",
  category: "/v2/categories/:slug/products",
} as const;

/** The name of a catalog API endpoint. */
export type EndpointName = keyof typeof ENDPOINTS;

/**
 * The URL of a catalog API endpoint: ``base`` (a trailing slash is dropped), the
 * endpoint's path with its path parameters filled in from ``params`` and
 * percent-encoded, and the other parameters as the query string. Throws a QueryError
 * when a path parameter is missing or is not a single value.
 */
export function endpointUrl(base: string, name: EndpointName, params: QueryParams = {}): string {
  const rest: Record<string, QueryValue> = { ...params };
  const path = ENDPOINTS[name].replace(/:([a-z]+)/g, (_match, key: string) => {
    const value = params[key];
    if (value === null || value === undefined || Array.isArray(value)) {
      throw new QueryError(`endpoint ${name} needs a single value for its ${key} parameter`);
    }
    delete rest[key];
    return encodeComponent(String(value));
  });
  return withQuery(`${base.replace(/\/+$/, "")}${path}`, rest);
}
