import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { main } from "../src/cli.ts";

function run(argv: string[]): { status: number; out: string; err: string } {
  let out = "";
  let err = "";
  const status = main(argv, {
    out: (text) => {
      out += text;
    },
    err: (text) => {
      err += text;
    },
  });
  return { status, out, err };
}

function changelog(text: string): string {
  const dir = mkdtempSync(join(tmpdir(), "changelog-lint-"));
  const path = join(dir, "CHANGELOG.md");
  writeFileSync(path, text);
  return path;
}

const CLEAN = "## [1.0.0] - 2026-01-02\n\n### Added\n\n- x\n";
const BROKEN = "## [1.0.0]\n\n### Misc\n\n- x\n\n## [0.9.0] - 2026-01-01\n";

test("a clean file exits 0", () => {
  const result = run([changelog(CLEAN)]);
  assert.equal(result.status, 0);
  assert.equal(result.out, "no problems found\n");
});

test("problems exit 1 and are listed before the summary", () => {
  const path = changelog(BROKEN);
  const result = run([path]);
  assert.equal(result.status, 1);
  const lines = result.out.trim().split("\n");
  assert.match(lines[0] ?? "", new RegExp(`^${path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}:1: date-format:`));
  assert.equal(lines.at(-1), "3 problems found");
});

test("--max-problems limits the printed lines but not the count", () => {
  const result = run([changelog(BROKEN), "--max-problems", "1"]);
  assert.equal(result.out.trim().split("\n").length, 2);
  assert.match(result.out, /3 problems found/);
});

test("--max-problems needs a positive whole number", () => {
  assert.equal(run(["--max-problems", "0"]).status, 2);
  assert.equal(run(["--max-problems", "x"]).status, 2);
});

test("a missing file exits 2 with a message on standard error", () => {
  const result = run(["/nonexistent/CHANGELOG.md"]);
  assert.equal(result.status, 2);
  assert.match(result.err, /^changelog-lint: .*cannot be read/);
});

test("an unknown option exits 2", () => {
  assert.equal(run(["--fix"]).status, 2);
});
