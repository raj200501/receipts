import assert from "node:assert/strict";
import { test } from "node:test";
import { readVersionList } from "../src/list.ts";

test("readVersionList skips blank lines and comments", () => {
  const text = "# release tags\nv2.7.0\n\n  v2.7.1  \n# hotfix\nv2.7.2\n";
  assert.deepEqual(readVersionList(text), ["v2.7.0", "v2.7.1", "v2.7.2"]);
});

test("readVersionList keeps each version as written", () => {
  assert.deepEqual(readVersionList("2.7.0+build.3\r\nv2.8.0-rc.1\r\n"), [
    "2.7.0+build.3",
    "v2.8.0-rc.1",
  ]);
});

test("readVersionList names the line of a bad version", () => {
  assert.throws(() => readVersionList("v2.7.0\n\nv2.8\n"), {
    name: "VersionError",
    message: 'line 3: not a version: "v2.8"',
  });
});
