import assert from "node:assert/strict";
import { test } from "node:test";
import { compareVersions, latestVersion, sortVersions } from "../src/compare.ts";

test("a prerelease is lower than its release", () => {
  assert.equal(compareVersions("2.8.0-rc.3", "2.8.0"), -1);
  assert.equal(compareVersions("v2.8.0", "v2.8.0-rc.3"), 1);
  assert.equal(compareVersions("2.8.0-rc.3+build.5", "2.8.0+build.1"), -1);
});

test("sort and latest put a release after its candidates", () => {
  const tags = ["v2.8.0", "v2.8.0-rc.3", "v2.7.1", "v2.8.0-rc.1"];
  assert.deepEqual(sortVersions(tags), ["v2.7.1", "v2.8.0-rc.1", "v2.8.0-rc.3", "v2.8.0"]);
  assert.equal(latestVersion(tags, { includePrerelease: true }), "v2.8.0");
});

test("numeric prerelease identifiers compare as numbers", () => {
  assert.equal(compareVersions("2.9.0-rc.9", "2.9.0-rc.10"), -1);
  assert.equal(compareVersions("2.9.0-beta.11", "2.9.0-beta.2"), 1);
  assert.deepEqual(sortVersions(["v2.9.0-rc.10", "v2.9.0-rc.9", "v2.9.0-rc.2"]), [
    "v2.9.0-rc.2",
    "v2.9.0-rc.9",
    "v2.9.0-rc.10",
  ]);
});

test("the example of docs/VERSIONING.md is in order", () => {
  const ordered = [
    "2.8.0-alpha",
    "2.8.0-alpha.2",
    "2.8.0-alpha.10",
    "2.8.0-alpha.preview",
    "2.8.0-beta",
    "2.8.0-rc.1",
    "2.8.0-rc.9",
    "2.8.0-rc.10",
    "2.8.0",
  ];
  const shuffled = [5, 0, 8, 3, 1, 7, 2, 6, 4].map((index) => ordered[index]);
  assert.deepEqual(sortVersions(shuffled), ordered);
});

test("a numeric identifier is lower than any other identifier", () => {
  assert.equal(compareVersions("3.0.0-1", "3.0.0-alpha"), -1);
  assert.equal(compareVersions("3.0.0-rc.1", "3.0.0-rc.a"), -1);
});

test("a shorter prerelease is lower when its identifiers match", () => {
  assert.equal(compareVersions("3.0.0-alpha", "3.0.0-alpha.1"), -1);
  assert.equal(compareVersions("3.0.0-x.y", "3.0.0-x-y"), -1);
});
