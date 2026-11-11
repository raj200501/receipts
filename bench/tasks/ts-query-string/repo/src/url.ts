/** Adding query parameters to URLs. */

import type { StringifyOptions } from "./stringify.ts";
import { stringify } from "./stringify.ts";
import type { QueryParams } from "./types.ts";

/**
 * ``url`` with ``params`` added to its query string: after any query the URL already
 * has and before its #fragment. The URL is returned unchanged when ``params`` write
 * nothing.
 */
export function withQuery(
  url: string,
  params: QueryParams,
  options: StringifyOptions = {},
): string {
  const query = stringify(params, options);
  if (query === "") {
    return url;
  }
  const hash = url.indexOf("#");
  const base = hash === -1 ? url : url.slice(0, hash);
  const fragment = hash === -1 ? "" : url.slice(hash);
  let separator = "?";
  if (base.includes("?")) {
    separator = base.endsWith("?") || base.endsWith("&") ? "" : "&";
  }
  return `${base}${separator}${query}${fragment}`;
}
