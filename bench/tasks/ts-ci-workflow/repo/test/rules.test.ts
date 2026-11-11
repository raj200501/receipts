import assert from "node:assert/strict";
import { test } from "node:test";
import { parseChangelog } from "../src/changelog.ts";
import { lint } from "../src/rules.ts";

function rulesFor(text: string): string[] {
  return lint(parseChangelog(text)).map((p) => p.rule);
}

const ENTRY = "\n### Added\n\n- x\n";

test("a clean changelog has no problems", () => {
  const text = `## [Unreleased]\n${ENTRY}\n## [1.1.0] - 2026-02-03\n${ENTRY}\n## [1.0.0] - 2026-01-02\n${ENTRY}`;
  assert.deepEqual(rulesFor(text), []);
});

test("version-format flags a heading that is not a version", () => {
  assert.deepEqual(rulesFor(`## [1.x] - 2026-01-02\n${ENTRY}`), ["version-format"]);
});

test("duplicate-version flags a repeated heading", () => {
  const text = `## [1.0.0] - 2026-01-02\n${ENTRY}\n## [1.0.0] - 2026-01-01\n${ENTRY}`;
  assert.ok(rulesFor(text).includes("duplicate-version"));
});

test("date-format flags a missing date and an impossible date", () => {
  assert.deepEqual(rulesFor(`## [1.0.0]\n${ENTRY}`), ["date-format"]);
  assert.deepEqual(rulesFor(`## [1.0.0] - 2026-02-30\n${ENTRY}`), ["date-format"]);
});

test("known-section flags an unknown section name", () => {
  assert.deepEqual(rulesFor("## [1.0.0] - 2026-01-02\n\n### Misc\n\n- x\n"), ["known-section"]);
});

test("empty-release flags a release without entries but not Unreleased", () => {
  assert.deepEqual(rulesFor("## [1.0.0] - 2026-01-02\n"), ["empty-release"]);
  assert.deepEqual(rulesFor("## [Unreleased]\n"), []);
});

test("order flags a release that is not older than the one above", () => {
  const text = `## [1.0.0] - 2026-01-02\n${ENTRY}\n## [1.1.0] - 2026-02-03\n${ENTRY}`;
  assert.deepEqual(rulesFor(text), ["order"]);
});

test("problems are ordered by line", () => {
  const text = `## [1.0.0] - 2026-01-02\n\n### Misc\n\n- x\n\n## [0.9.0]\n${ENTRY}`;
  const lines = lint(parseChangelog(text)).map((p) => p.line);
  assert.deepEqual(lines, [...lines].sort((a, b) => a - b));
});
