/** Page-number pagination. */

import { resolveSize } from "./limits.ts";
import type { OffsetOptions, OffsetPage } from "./types.ts";

/** Cut one page out of a list. Pages past the end are empty, not an error. */
export function paginate<T>(items: readonly T[], options: OffsetOptions = {}): OffsetPage<T> {
  const page = options.page ?? 1;
  if (!Number.isInteger(page) || page < 1) {
    throw new RangeError(`page must be a whole number of at least 1, got ${page}`);
  }
  const perPage = resolveSize(options.perPage);
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const start = (page - 1) * perPage;
  return {
    items: items.slice(start, start + perPage),
    page,
    perPage,
    total,
    totalPages,
    hasNext: page < totalPages,
    hasPrev: page > 1,
  };
}
