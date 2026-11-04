import assert from "node:assert/strict";
import { test } from "node:test";
import { linkHeader, pageLinks } from "../src/links.ts";
import { paginate } from "../src/offset.ts";

const ITEMS = Array.from({ length: 45 }, (_, index) => index);

test("pageLinks on a middle page has all four links", () => {
  assert.deepEqual(pageLinks("/orders", paginate(ITEMS, { page: 2, perPage: 10 })), {
    first: "/orders?page=1&per_page=10",
    prev: "/orders?page=1&per_page=10",
    next: "/orders?page=3&per_page=10",
    last: "/orders?page=5&per_page=10",
  });
});

test("pageLinks has no prev on the first page and no next on the last", () => {
  const first = pageLinks("/orders", paginate(ITEMS, { page: 1, perPage: 10 }));
  assert.equal(first.prev, null);
  const last = pageLinks("/orders", paginate(ITEMS, { page: 5, perPage: 10 }));
  assert.equal(last.next, null);
});

test("pageLinks appends to a base path that already has a query", () => {
  const links = pageLinks("/orders?status=open", paginate(ITEMS, { page: 1, perPage: 20 }));
  assert.equal(links.next, "/orders?status=open&page=2&per_page=20");
});

test("linkHeader formats the links and leaves out missing ones", () => {
  assert.equal(
    linkHeader("/orders", paginate(ITEMS, { page: 1, perPage: 30 })),
    '</orders?page=1&per_page=30>; rel="first", </orders?page=2&per_page=30>; rel="next", </orders?page=2&per_page=30>; rel="last"',
  );
});
