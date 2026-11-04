import assert from "node:assert/strict";
import { test } from "node:test";
import { withQuery } from "../src/url.ts";

const BASE = "https://catalog.example.invalid/v2/search";

test("withQuery adds a query string to a URL without one", () => {
  assert.equal(withQuery(BASE, { q: "socks", page: 2 }), `${BASE}?q=socks&page=2`);
});

test("withQuery adds to the query the URL already has", () => {
  assert.equal(withQuery(`${BASE}?lang=en`, { page: 2 }), `${BASE}?lang=en&page=2`);
  assert.equal(withQuery(`${BASE}?`, { page: 2 }), `${BASE}?page=2`);
});

test("withQuery keeps the fragment at the end", () => {
  assert.equal(withQuery(`${BASE}?lang=en#results`, { page: 2 }), `${BASE}?lang=en&page=2#results`);
  assert.equal(withQuery(`${BASE}#results`, { page: 2 }), `${BASE}?page=2#results`);
});

test("withQuery returns the URL unchanged when there is nothing to add", () => {
  assert.equal(withQuery(`${BASE}?lang=en#results`, {}), `${BASE}?lang=en#results`);
  assert.equal(withQuery(BASE, { color: null }), BASE);
});

test("withQuery passes the sort option on", () => {
  assert.equal(withQuery(BASE, { sort: "price", page: 2 }, { sort: true }), `${BASE}?page=2&sort=price`);
});
