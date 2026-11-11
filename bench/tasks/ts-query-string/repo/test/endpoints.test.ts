import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryError } from "../src/encode.ts";
import { ENDPOINTS, endpointUrl } from "../src/endpoints.ts";

const BASE = "https://catalog.example.invalid";

test("every endpoint has a path under /v2", () => {
  for (const path of Object.values(ENDPOINTS)) {
    assert.match(path, /^\/v2\//);
  }
});

test("search has no path parameters", () => {
  assert.equal(endpointUrl(BASE, "search", { q: "socks", page: 2 }), `${BASE}/v2/search?q=socks&page=2`);
});

test("path parameters are filled in and left out of the query string", () => {
  assert.equal(endpointUrl(BASE, "reviews", { id: "sku-1042", page: 2 }), `${BASE}/v2/products/sku-1042/reviews?page=2`);
  assert.equal(endpointUrl(BASE, "product", { id: 1042 }), `${BASE}/v2/products/1042`);
});

test("path parameters are percent-encoded", () => {
  assert.equal(endpointUrl(BASE, "category", { slug: "socks/wool" }), `${BASE}/v2/categories/socks%2Fwool/products`);
});

test("a missing path parameter is a QueryError", () => {
  assert.throws(() => endpointUrl(BASE, "product", { lang: "en" }), {
    name: "QueryError",
    message: "endpoint product needs a single value for its id parameter",
  });
  assert.throws(() => endpointUrl(BASE, "product", { id: ["a", "b"] }), QueryError);
});

test("a trailing slash on the base URL is dropped", () => {
  assert.equal(endpointUrl(`${BASE}/`, "search", { q: "socks" }), `${BASE}/v2/search?q=socks`);
});
