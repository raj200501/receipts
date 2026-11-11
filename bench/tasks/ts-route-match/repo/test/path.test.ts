import assert from "node:assert/strict";
import { test } from "node:test";
import { decodeValue, requestPath } from "../src/path.ts";

test("the path of a target leaves out the query string and the fragment", () => {
  assert.equal(requestPath("/v2/orders?limit=5"), "/v2/orders");
  assert.equal(requestPath("/v2/orders#top"), "/v2/orders");
  assert.equal(requestPath("/"), "/");
});

test("a target must start with a slash", () => {
  assert.throws(() => requestPath("v2/orders"), {
    name: "PathError",
    message: 'the request target must start with /, got "v2/orders"',
  });
  assert.throws(() => requestPath("?q=1"), { name: "PathError" });
});

test("values are percent-decoded", () => {
  assert.equal(decodeValue("Ada%20L"), "Ada L");
  assert.equal(decodeValue("caf%C3%A9"), "caf\u00e9");
  assert.equal(decodeValue("plain"), "plain");
});

test("broken percent-encoding is a PathError", () => {
  assert.throws(() => decodeValue("100%"), /invalid percent-encoding in "100%"/);
});
