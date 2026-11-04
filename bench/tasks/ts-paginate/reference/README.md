# pager

Pagination helpers for list endpoints. Hand-written example project for receipts-bench
(synthetic). Everything is exported from `src/index.ts`.

## Page numbers

    import { paginate, parsePageParams, pageLinks, linkHeader } from "./src/index.ts";

    const { page, perPage } = parsePageParams({ page: "2", per_page: "10" });
    const result = paginate(rows, { page, perPage });
    const links = pageLinks("/orders", result);
    const header = linkHeader("/orders", result);

`paginate(items, { page, perPage })` returns `{ items, page, perPage, total, totalPages,
hasNext, hasPrev }`. The page defaults to 1. A page past the end is empty, not an error,
and an empty list has one empty page. A `page` that is not a whole number of at least 1
throws a `RangeError`.

`parsePageParams(query)` reads the `page` and `per_page` strings of a query. Missing
values mean page 1 and the default size. Other parameters are ignored. A value that is not
a positive whole number throws a `PageParamsError`, which the API turns into a 400.

`pageLinks(basePath, result)` gives `first`, `prev`, `next`, and `last` as
`/orders?page=2&per_page=10`; `prev` and `next` are `null` at the ends. `linkHeader`
formats the same links as an HTTP `Link` header.

## Cursor pages

    import { paginateCursor, parseCursorParams } from "./src/index.ts";

    const { cursor, limit } = parseCursorParams({ cursor: req.query.cursor, limit: "25" });
    const page = paginateCursor(rows, { cursor, limit });
    // page.items, page.nextCursor (null on the last page), page.hasMore

Cursor pages suit lists that change while people page through them. Rows need a numeric
`id`; `paginateCursor` returns them in ascending id order, `limit` of them after the
cursor (the first rows when there is no cursor). `nextCursor` is an opaque URL-safe string
that stands for the last id returned, not a position, so rows added or removed between
two requests do not make a page repeat or skip rows. A cursor that `paginateCursor` did not
produce throws an `InvalidCursorError`.

`limit` follows the page size rules below. `parseCursorParams(query)` reads `cursor` and
`limit` from a query (no cursor gives `null`; a bad `limit` throws a `PageParamsError`).
A query with both `page` and `cursor` is ambiguous, so `parsePageParams` rejects it with
a `PageParamsError`.

## Page sizes

The default page size is 20 and the largest is 100, for page numbers and cursors alike.
A larger size is cut down to 100, and a size that is not a whole number of at least 1 throws a `RangeError`
(`resolveSize` in `src/limits.ts`).

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
