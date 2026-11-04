import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryError, decodeComponent, encodeComponent } from "../src/encode.ts";

test("letters, digits, and - . _ ~ are written as they are", () => {
  assert.equal(encodeComponent("Az09-._~"), "Az09-._~");
});

test("reserved characters are percent-encoded", () => {
  assert.equal(encodeComponent("a&b=c/d?e#f"), "a%26b%3Dc%2Fd%3Fe%23f");
  assert.equal(encodeComponent("+,;:@$"), "%2B%2C%3B%3A%40%24");
  assert.equal(encodeComponent("(1*2)!'"), "%281%2A2%29%21%27");
});

test("text is encoded as UTF-8 with upper-case hex digits", () => {
  assert.equal(encodeComponent("café"), "caf%C3%A9");
  assert.equal(encodeComponent("€5"), "%E2%82%AC5");
});

test("text with a lone surrogate cannot be encoded", () => {
  assert.throws(() => encodeComponent("\uD800"), QueryError);
});

test("decodeComponent reads percent escapes and + as a space", () => {
  assert.equal(decodeComponent("caf%C3%A9"), "café");
  assert.equal(decodeComponent("red+shoes%20size"), "red shoes size");
  assert.equal(decodeComponent("c%2B%2B"), "c++");
});

test("a malformed percent escape is a QueryError", () => {
  assert.throws(() => decodeComponent("100%"), {
    name: "QueryError",
    message: 'malformed percent escape in "100%"',
  });
});
