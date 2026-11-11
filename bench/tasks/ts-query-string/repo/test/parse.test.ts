import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryError } from "../src/encode.ts";
import { parse } from "../src/parse.ts";

test("each key maps to its value", () => {
  assert.deepEqual(parse("q=socks&page=2"), { q: "socks", page: "2" });
});

test("a leading ? is ignored", () => {
  assert.deepEqual(parse("?q=socks"), { q: "socks" });
  assert.deepEqual(parse("?"), {});
});

test("a repeated key maps to an array of its values in order", () => {
  assert.deepEqual(parse("tag=sale&page=1&tag=new&tag=gift"), {
    tag: ["sale", "new", "gift"],
    page: "1",
  });
});

test("+ and %20 both read as a space", () => {
  assert.deepEqual(parse("q=red+running%20shoes"), { q: "red running shoes" });
});

test("a key without = maps to an empty string and empty pairs are skipped", () => {
  assert.deepEqual(parse("inStock&&q=socks&color="), { inStock: "", q: "socks", color: "" });
});

test("a malformed percent escape is a QueryError", () => {
  assert.throws(() => parse("q=100%"), QueryError);
  assert.throws(() => parse("q=%E2%82"), QueryError);
});

test("__proto__ is read as an ordinary key", () => {
  const result = parse("__proto__=x&q=socks");
  assert.equal(Object.getPrototypeOf(result), Object.prototype);
  assert.deepEqual(Object.keys(result), ["__proto__", "q"]);
  assert.equal(Object.getOwnPropertyDescriptor(result, "__proto__")?.value, "x");
});
