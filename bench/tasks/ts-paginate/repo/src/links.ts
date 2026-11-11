/** Links between pages, for a Link header or a JSON response body. */

import type { OffsetPage, PageLinks } from "./types.ts";

function href(basePath: string, page: number, perPage: number): string {
  const separator = basePath.includes("?") ? "&" : "?";
  return `${basePath}${separator}page=${page}&per_page=${perPage}`;
}

/** The links of a page: first, previous, next, and last. */
export function pageLinks(basePath: string, result: OffsetPage<unknown>): PageLinks {
  const { page, perPage, totalPages } = result;
  return {
    first: href(basePath, 1, perPage),
    prev: result.hasPrev ? href(basePath, page - 1, perPage) : null,
    next: result.hasNext ? href(basePath, page + 1, perPage) : null,
    last: href(basePath, totalPages, perPage),
  };
}

/** The same links as the value of an HTTP Link header. */
export function linkHeader(basePath: string, result: OffsetPage<unknown>): string {
  const links = pageLinks(basePath, result);
  const parts: string[] = [];
  for (const rel of ["first", "prev", "next", "last"] as const) {
    const target = links[rel];
    if (target !== null) {
      parts.push(`<${target}>; rel="${rel}"`);
    }
  }
  return parts.join(", ");
}
