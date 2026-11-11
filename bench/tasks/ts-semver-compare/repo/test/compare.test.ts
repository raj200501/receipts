import assert from "node:assert/strict";
import { test } from "node:test";
import { compareVersions, latestVersion, sortVersions } from "../src/compare.ts";
import { parseVersion } from "../src/version.ts";

test("major, minor, and patch compare as numbers", () => {
  assert.equal(compareVersions("1.9.0", "1.10.0"), -1);
  assert.equal(compareVersions("1.10.0", "2.0.0"), -1);
  assert.equal(compareVersions("10.0.0", "9.9.9"), 1);
  assert.equal(compareVersions("2.7.10", "2.7.9"), 1);
});

test("the same version with and without v compares as equal", () => {
  assert.equal(compareVersions("2.7.1", "v2.7.1"), 0);
});

test("build metadata does not count", () => {
  assert.equal(compareVersions("2.8.0+build.12", "2.8.0+build.7"), 0);
});

test("compareVersions also takes parsed versions", () => {
  assert.equal(compareVersions(parseVersion("2.7.1"), "2.7.2"), -1);
});

test("a prerelease of a later release is higher than an earlier release", () => {
  assert.equal(compareVersions("2.8.0-rc.1", "2.7.9"), 1);
  assert.equal(compareVersions("2.7.9", "3.0.0-alpha"), -1);
});

test("prerelease names compare alphabetically", () => {
  assert.equal(compareVersions("3.0.0-alpha", "3.0.0-beta"), -1);
  assert.equal(compareVersions("3.0.0-rc", "3.0.0-beta"), 1);
});

test("sortVersions orders releases from lowest to highest as written", () => {
  assert.deepEqual(sortVersions(["v2.10.0", "v2.7.1", "v2.9.3", "v1.12.0"]), [
    "v1.12.0",
    "v2.7.1",
    "v2.9.3",
    "v2.10.0",
  ]);
});

test("sortVersions with reverse puts the highest version first", () => {
  assert.deepEqual(sortVersions(["2.7.1", "2.10.0", "2.9.3"], { reverse: true }), [
    "2.10.0",
    "2.9.3",
    "2.7.1",
  ]);
});

test("equal versions keep their order", () => {
  assert.deepEqual(sortVersions(["2.8.0+build.12", "2.7.0", "2.8.0+build.7"]), [
    "2.7.0",
    "2.8.0+build.12",
    "2.8.0+build.7",
  ]);
});

test("latestVersion skips prereleases unless asked to include them", () => {
  const versions = ["2.7.1", "2.8.0-rc.1", "2.6.4"];
  assert.equal(latestVersion(versions), "2.7.1");
  assert.equal(latestVersion(versions, { includePrerelease: true }), "2.8.0-rc.1");
  assert.equal(latestVersion(["2.8.0-rc.1"]), null);
});
