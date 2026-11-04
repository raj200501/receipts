import assert from "node:assert/strict";
import { test } from "node:test";
import { entryCount, parseChangelog } from "../src/changelog.ts";

const TEXT = `# Changelog

## [Unreleased]

### Added

- Draft entry.

## [1.1.0] - 2026-02-03

### Added

- First thing.
* Second thing.

### Fixed

- A bug.

## [1.0.0] - 2026-01-02
`;

test("parseChangelog finds the releases in order", () => {
  const releases = parseChangelog(TEXT);
  assert.deepEqual(releases.map((r) => r.version), ["Unreleased", "1.1.0", "1.0.0"]);
});

test("a release heading carries its date and line", () => {
  const [, release] = parseChangelog(TEXT);
  assert.equal(release?.date, "2026-02-03");
  assert.equal(release?.line, 9);
});

test("the Unreleased heading has no date", () => {
  assert.equal(parseChangelog(TEXT)[0]?.date, null);
});

test("sections and entries are collected under their release", () => {
  const release = parseChangelog(TEXT)[1];
  assert.deepEqual(release?.sections.map((s) => [s.name, s.entries.length]), [["Added", 2], ["Fixed", 1]]);
  assert.equal(release?.sections[0]?.entries[1], "Second thing.");
});

test("entryCount adds up all sections", () => {
  assert.equal(entryCount(parseChangelog(TEXT)[1]!), 3);
  assert.equal(entryCount(parseChangelog(TEXT)[2]!), 0);
});

test("text before the first release is ignored", () => {
  assert.equal(parseChangelog("# Title\n\n- stray bullet\n").length, 0);
});

test("CRLF line endings are accepted", () => {
  assert.equal(parseChangelog("## [1.0.0] - 2026-01-02\r\n\r\n### Added\r\n\r\n- x\r\n").length, 1);
});
