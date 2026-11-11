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

## Page sizes

The default page size is 20 and the largest is 100. A larger size is cut down to 100,
and a size that is not a whole number of at least 1 throws a `RangeError`
(`resolveSize` in `src/limits.ts`).

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
