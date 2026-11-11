/** Reading query strings back into objects. */

import { decodeComponent } from "./encode.ts";
import type { ParsedQuery } from "./types.ts";

/** Add one value under ``key``; a key seen before collects its values in an array. */
function add(result: ParsedQuery, key: string, value: string): void {
  if (!Object.hasOwn(result, key)) {
    // defineProperty, so that a key such as "__proto__" stays an ordinary key.
    Object.defineProperty(result, key, {
      value,
      enumerable: true,
      writable: true,
      configurable: true,
    });
    return;
  }
  const existing = result[key];
  result[key] = Array.isArray(existing) ? [...existing, value] : [existing, value];
}

/**
 * Parse a query string, with or without a leading "?". A key that appears once maps
 * to its value, a repeated key to an array of its values in order, and a key without
 * "=" to "". Empty pairs ("a=1&&b=2") are skipped. Both "+" and "%20" read as a space.
 * Throws a QueryError for a malformed percent escape.
 */
export function parse(query: string): ParsedQuery {
  const text = query.startsWith("?") ? query.slice(1) : query;
  const result: ParsedQuery = {};
  for (const pair of text.split("&")) {
    if (pair === "") {
      continue;
    }
    const equals = pair.indexOf("=");
    const key = decodeComponent(equals === -1 ? pair : pair.slice(0, equals));
    const value = equals === -1 ? "" : decodeComponent(pair.slice(equals + 1));
    add(result, key, value);
  }
  return result;
}
