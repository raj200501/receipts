import assert from "node:assert/strict";
import { test } from "node:test";
import { compareVersions, parseVersion } from "../src/semver.ts";

function cmp(a: string, b: string): number {
  return Math.sign(compareVersions(parseVersion(a)!, parseVersion(b)!));
}

test("parseVersion reads release and prerelease versions", () => {
  assert.deepEqual(parseVersion("1.2.3"), { major: 1, minor: 2, patch: 3, prerelease: [] });
  assert.deepEqual(parseVersion("1.2.3-rc.1")?.prerelease, ["rc", "1"]);
});

test("parseVersion rejects other text", () => {
  assert.equal(parseVersion("1.2"), null);
  assert.equal(parseVersion("v1.2.3"), null);
  assert.equal(parseVersion("Unreleased"), null);
});

test("versions compare by major, minor, then patch", () => {
  assert.equal(cmp("2.0.0", "1.9.9"), 1);
  assert.equal(cmp("1.2.0", "1.10.0"), -1);
  assert.equal(cmp("1.2.3", "1.2.3"), 0);
});

test("a prerelease is older than its release", () => {
  assert.equal(cmp("1.0.0-rc.1", "1.0.0"), -1);
  assert.equal(cmp("1.0.0", "1.0.0-rc.1"), 1);
});

test("prerelease identifiers compare numerically when both are numbers", () => {
  assert.equal(cmp("1.0.0-rc.2", "1.0.0-rc.10"), -1);
  assert.equal(cmp("1.0.0-alpha", "1.0.0-beta"), -1);
  assert.equal(cmp("1.0.0-1", "1.0.0-alpha"), -1);
  assert.equal(cmp("1.0.0-alpha", "1.0.0-alpha.1"), -1);
});
