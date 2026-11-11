import assert from "node:assert/strict";
import { test } from "node:test";
import { parse } from "../src/parse.ts";
import { stringify } from "../src/stringify.ts";

test("pairs are written in the order of the object", () => {
  assert.equal(stringify({ q: "socks", page: 2, sort: "price" }), "q=socks&page=2&sort=price");
});

test("numbers and booleans are written as text", () => {
  assert.equal(stringify({ page: 3, minPrice: 9.5, inStock: true, used: false }), "page=3&minPrice=9.5&inStock=true&used=false");
});

test("null and undefined values are left out", () => {
  assert.equal(stringify({ q: "socks", color: null, size: undefined, page: 1 }), "q=socks&page=1");
});

test("keys and values are percent-encoded", () => {
  assert.equal(stringify({ "a&b": "c=d/e", brand: "Strümpfli" }), "a%26b=c%3Dd%2Fe&brand=Str%C3%BCmpfli");
});

test("sort writes the keys in sorted order", () => {
  assert.equal(stringify({ sort: "price", page: 2, q: "socks" }, { sort: true }), "page=2&q=socks&sort=price");
});

test("an empty object gives an empty query string", () => {
  assert.equal(stringify({}), "");
  assert.equal(stringify({ color: null }), "");
});

test("values with reserved characters read back the same", () => {
  const params = { q: "50%-off", ref: "mail?id=7&src=news" };
  assert.deepEqual(parse(stringify(params)), params);
});

// Saved searches (ticket SHOP-2291): the account page finds a shopper's saved search by
// comparing the query string we build with the one stored when the search was saved,
// and the stored ones write a space in a value as "+". Keep writing it that way.
test("a space in a value is written as + so that saved searches still match", () => {
  assert.equal(stringify({ q: "wool socks" }), "q=wool+socks");
  assert.equal(stringify({ q: "socks", brand: "Blue Fox" }), "q=socks&brand=Blue+Fox");
});
