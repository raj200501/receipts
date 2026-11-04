import assert from "node:assert/strict";
import { test } from "node:test";
import { VersionError, formatVersion, isPrerelease, parseVersion } from "../src/version.ts";

test("parseVersion reads every part of a version", () => {
  assert.deepEqual(parseVersion("2.8.0-beta.3+build.4410"), {
    major: 2,
    minor: 8,
    patch: 0,
    prerelease: ["beta", "3"],
    build: ["build", "4410"],
    tagged: false,
  });
});

test("a leading v is accepted and remembered", () => {
  const version = parseVersion("v2.7.1");
  assert.equal(version.tagged, true);
  assert.equal(formatVersion(version), "v2.7.1");
  assert.equal(formatVersion(version, { tag: false }), "2.7.1");
});

test("formatVersion writes the prerelease and the build metadata", () => {
  assert.equal(formatVersion(parseVersion("1.0.0-rc.1+sha.9e1c2d4")), "1.0.0-rc.1+sha.9e1c2d4");
});

test("isPrerelease is true only for a version with a prerelease part", () => {
  assert.equal(isPrerelease(parseVersion("2.8.0-rc.1")), true);
  assert.equal(isPrerelease(parseVersion("2.8.0+build.7")), false);
});

test("incomplete and malformed versions are rejected", () => {
  for (const text of ["", "2.8", "2.8.0.1", "v", "2.8.x", "2.8.0-", "2.8.0+", "2.8.0 beta"]) {
    assert.throws(() => parseVersion(text), VersionError, JSON.stringify(text));
  }
});

test("leading zeros are rejected in numbers and numeric prerelease identifiers", () => {
  assert.throws(() => parseVersion("02.8.0"), /leading zero in 02/);
  assert.throws(() => parseVersion("2.8.0-rc.01"), /leading zero in 01/);
  assert.deepEqual(parseVersion("2.8.0+build.007").build, ["build", "007"]);
});

test("empty prerelease identifiers are rejected", () => {
  assert.throws(() => parseVersion("2.8.0-rc..1"), {
    name: "VersionError",
    message: 'not a version: "2.8.0-rc..1" (empty identifier)',
  });
});
