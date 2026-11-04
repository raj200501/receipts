import assert from "node:assert/strict";
import { test } from "node:test";
import { bumpVersion } from "../src/bump.ts";

test("major, minor, and patch reset the numbers after them", () => {
  assert.equal(bumpVersion("2.7.1", "major"), "3.0.0");
  assert.equal(bumpVersion("2.7.1", "minor"), "2.8.0");
  assert.equal(bumpVersion("2.7.1", "patch"), "2.7.2");
});

test("a level bump drops the prerelease and the build metadata", () => {
  assert.equal(bumpVersion("2.8.0-rc.2+build.81", "minor"), "2.9.0");
});

test("a leading v is kept", () => {
  assert.equal(bumpVersion("v2.7.1", "patch"), "v2.7.2");
  assert.equal(bumpVersion("v2.7.1", "pre"), "v2.7.2-rc.1");
});

test("pre starts the first release candidate of the next patch", () => {
  assert.equal(bumpVersion("2.7.1", "pre"), "2.7.2-rc.1");
});

test("pre counts up the release candidate", () => {
  assert.equal(bumpVersion("2.8.0-rc.2", "pre"), "2.8.0-rc.3");
  assert.equal(bumpVersion("2.8.0-rc.9", "pre"), "2.8.0-rc.10");
});

test("pre with another name starts that name at 1", () => {
  assert.equal(bumpVersion("2.8.0-alpha.4", "pre", "beta"), "2.8.0-beta.1");
  assert.throws(() => bumpVersion("2.8.0", "pre", "1x"), /not a prerelease name/);
});

test("release drops the prerelease part", () => {
  assert.equal(bumpVersion("2.8.0-rc.3", "release"), "2.8.0");
  assert.throws(() => bumpVersion("2.8.0", "release"), /2\.8\.0 is not a prerelease/);
});
