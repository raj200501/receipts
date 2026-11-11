import assert from "node:assert/strict";
import { test } from "node:test";
import { publishedVersions, registryToken, versionsUrl } from "../src/registry.ts";

test("the versions URL names the package", () => {
  assert.equal(
    versionsUrl("vercmp"),
    "https://registry.build.internal/api/v2/packages/vercmp/versions",
  );
});

test("scoped package names are escaped in the versions URL", () => {
  assert.equal(
    versionsUrl("@release/vercmp", "https://registry.example.invalid"),
    "https://registry.example.invalid/packages/%40release%2Fvercmp/versions",
  );
});

test("the registry token is read from REGISTRY_TOKEN", () => {
  assert.equal(registryToken({ REGISTRY_TOKEN: "ci-token" }), "ci-token");
  assert.throws(() => registryToken({}), /REGISTRY_TOKEN is not set/);
});

test("lists the published versions of vercmp", async () => {
  // Needs the REGISTRY_TOKEN secret and the build network; only the CI runners have both.
  const versions = await publishedVersions("vercmp");
  assert.ok(versions.includes("1.6.0"), versions.join(", "));
});
