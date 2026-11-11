/** Cursor-based pagination: pages that continue after the last item the caller saw. */

import { resolveSize } from "./limits.ts";

/** Thrown for a cursor that this library did not produce. The API answers 400. */
export class InvalidCursorError extends Error {
  constructor(message = "invalid cursor") {
    super(message);
    this.name = "InvalidCursorError";
  }
}

/** Items that can be paged through by cursor have a numeric id; ids are unique. */
export interface Identified {
  id: number;
}

/** Options of `paginateCursor`. */
export interface CursorOptions {
  /** Items per page; see `resolveSize` for the default and the limit. */
  limit?: number;
  /** The `nextCursor` of the previous page; leave out for the first page. */
  cursor?: string | null;
}

/** One page of a cursor-paged list. */
export interface CursorPage<T> {
  items: T[];
  /** Pass this as `cursor` to get the next page; null when there are no more items. */
  nextCursor: string | null;
  hasMore: boolean;
}

const VERSION = 1;

/** The opaque cursor that continues after the item with this id. */
export function encodeCursor(afterId: number): string {
  return Buffer.from(JSON.stringify({ v: VERSION, after: afterId }), "utf8").toString("base64url");
}

/** The id that a cursor continues after. Throws InvalidCursorError for anything else. */
export function decodeCursor(cursor: string): number {
  if (!/^[A-Za-z0-9_-]+$/.test(cursor)) {
    throw new InvalidCursorError();
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
  } catch {
    throw new InvalidCursorError();
  }
  const fields = parsed as { v?: unknown; after?: unknown } | null;
  if (
    typeof fields !== "object" ||
    fields === null ||
    fields.v !== VERSION ||
    typeof fields.after !== "number" ||
    !Number.isSafeInteger(fields.after)
  ) {
    throw new InvalidCursorError();
  }
  if (encodeCursor(fields.after) !== cursor) {
    throw new InvalidCursorError();
  }
  return fields.after;
}

/**
 * Cut one page out of a list, in ascending id order, starting after the cursor.
 *
 * The cursor stands for an id, not a position, so items added or removed between two
 * requests do not make the next page repeat or skip items.
 */
export function paginateCursor<T extends Identified>(
  items: readonly T[],
  options: CursorOptions = {},
): CursorPage<T> {
  const limit = resolveSize(options.limit);
  const after =
    options.cursor === undefined || options.cursor === null
      ? Number.NEGATIVE_INFINITY
      : decodeCursor(options.cursor);
  const ordered = items.filter((item) => item.id > after).sort((a, b) => a.id - b.id);
  const page = ordered.slice(0, limit);
  const hasMore = ordered.length > limit;
  const last = page.at(-1);
  return {
    items: page,
    nextCursor: hasMore && last !== undefined ? encodeCursor(last.id) : null,
    hasMore,
  };
}
