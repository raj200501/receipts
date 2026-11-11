import assert from "node:assert/strict";
import { test } from "node:test";
import { REGISTRY_URL, registryAuthHeader, registryToken } from "../src/registry.ts";

test("the registry URL uses https", () => {
  assert.ok(REGISTRY_URL.startsWith("https://"));
});

test("registryToken reads the token from the given environment", () => {
  assert.equal(registryToken({ REGISTRY_TOKEN: "abc" }), "abc");
});

test("registryToken rejects an empty token", () => {
  assert.throws(() => registryToken({ REGISTRY_TOKEN: "" }), /REGISTRY_TOKEN/);
});

test("authenticates to the internal package registry with the CI token", () => {
  // Needs the REGISTRY_TOKEN secret, which only the platform team's CI provides.
  assert.match(registryAuthHeader(), /^Bearer .+/);
});
