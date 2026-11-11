import assert from "node:assert/strict";
import { test } from "node:test";
import { letterCounts, mean, median } from "../src/stats.ts";
import type { StudentResult } from "../src/types.ts";

function result(student: string, letter: string): StudentResult {
  const categories = { homework: 0, quizzes: 0, project: 0, exams: 0 };
  return { student, name: student, categories, percent: 0, letter };
}

test("mean of the final percentages", () => {
  assert.equal(mean([80, 90, 100]), 90);
  assert.equal(mean([]), 0);
});

test("median of an odd number of values", () => {
  assert.equal(median([91, 60, 75]), 75);
});

test("median of an even number of values", () => {
  assert.equal(median([60, 70, 80, 90]), 75);
});

test("letter counts list the best letter first and skip letters nobody got", () => {
  const results = [result("s1", "B"), result("s2", "A"), result("s3", "B")];
  assert.deepEqual(letterCounts(results), [
    ["A", 1],
    ["B", 2],
  ]);
});
