import assert from "node:assert/strict";
import { test } from "node:test";
import { HEADER, ScoreError, parseRow, parseScores } from "../src/scores.ts";

test("parseRow reads every field", () => {
  const row = parseRow("s01,Ada Lovelace,hw1,homework,9,10", 2);
  assert.deepEqual(row, {
    student: "s01",
    name: "Ada Lovelace",
    assignment: "hw1",
    category: "homework",
    points: 9,
    maxPoints: 10,
    line: 2,
  });
});

test("empty points mean missing work", () => {
  assert.equal(parseRow("s01,Ada,hw1,homework,,10", 2).points, null);
});

test("EX marks an excused assignment", () => {
  assert.equal(parseRow("s01,Ada,hw1,homework,EX,10", 2).points, "EX");
});

test("unknown categories are rejected with the line number", () => {
  assert.throws(() => parseRow("s01,Ada,lab1,labs,5,10", 7), {
    name: "ScoreError",
    message: 'line 7: unknown category "labs"',
  });
});

test("rows need six fields", () => {
  assert.throws(() => parseRow("s01,Ada,hw1,homework,9", 3), /line 3: expected 6 fields/);
});

test("negative points and a zero maximum are rejected", () => {
  assert.throws(() => parseRow("s01,Ada,hw1,homework,-1,10", 4), /points must be a number/);
  assert.throws(() => parseRow("s01,Ada,hw1,homework,1,0", 4), /greater than 0/);
});

test("parseScores needs the header", () => {
  assert.throws(() => parseScores("s01,Ada,hw1,homework,9,10\n"), ScoreError);
});

test("parseScores skips blank lines and keeps line numbers", () => {
  const text = `${HEADER}\n\ns01,Ada,hw1,homework,9,10\n\ns01,Ada,q1,quizzes,8,10\n`;
  assert.deepEqual(
    parseScores(text).map((row) => row.line),
    [3, 5],
  );
});
