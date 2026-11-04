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

function scoresFile(text: string): string {
  const path = join(mkdtempSync(join(tmpdir(), "gradebook-")), "scores.csv");
  writeFileSync(path, text);
  return path;
}

const HEADER = "student,name,assignment,category,points,max_points\n";

test("report prints the class report", () => {
  const path = scoresFile(`${HEADER}s01,Ada,hw1,homework,9,10\ns01,Ada,q1,quizzes,9,10\n`);
  const { status, out } = run(["report", path]);
  assert.equal(status, 0);
  assert.match(out, /^student name/);
  assert.match(out, /students: 1\n/);
});

test("an unreadable file exits with status 2", () => {
  const { status, err } = run(["report", join(tmpdir(), "does-not-exist", "scores.csv")]);
  assert.equal(status, 2);
  assert.match(err, /^gradebook: cannot read /);
});

test("a bad row exits with status 2 and names the line", () => {
  const path = scoresFile(`${HEADER}s01,Ada,hw1,homework,9,10\ns01,Ada,q1,quiz,9,10\n`);
  const { status, out, err } = run(["report", path]);
  assert.equal(status, 2);
  assert.equal(out, "");
  assert.equal(err, 'gradebook: line 3: unknown category "quiz"\n');
});

test("anything else prints the usage", () => {
  const { status, err } = run(["summary"]);
  assert.equal(status, 2);
  assert.match(err, /^usage: gradebook report FILE/);
});
