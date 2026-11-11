import assert from "node:assert/strict";
import { test } from "node:test";
import { STAGING_URL, isSupported, serverVersion, versionUrl } from "../src/version.ts";

test("the version endpoint is under the base URL", () => {
  assert.equal(versionUrl("https://catalog.example.invalid"), "https://catalog.example.invalid/version");
});

test("a trailing slash on the base URL is dropped for the version endpoint", () => {
  assert.equal(versionUrl("https://catalog.example.invalid/"), "https://catalog.example.invalid/version");
});

test("the client supports API version 2 only", () => {
  assert.equal(isSupported(2), true);
  assert.equal(isSupported(1), false);
  assert.equal(isSupported(3), false);
});

test("the staging catalog runs a supported API version", async () => {
  // Needs the deploy network: catalog.staging.internal is not reachable from anywhere else.
  assert.equal(isSupported(await serverVersion(STAGING_URL)), true);
});
