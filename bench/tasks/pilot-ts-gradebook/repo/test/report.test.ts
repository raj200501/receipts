import assert from "node:assert/strict";
import { test } from "node:test";
import { formatPercent, renderReport } from "../src/report.ts";
import type { StudentResult } from "../src/types.ts";

const ADA: StudentResult = {
  student: "s01",
  name: "Ada Lovelace",
  categories: { homework: 95, quizzes: 87.5, project: 92, exams: 90.5 },
  percent: 91.6,
  letter: "A-",
};

test("percentages have one decimal place", () => {
  assert.equal(formatPercent(87.25), "87.3");
  assert.equal(formatPercent(90), "90.0");
  assert.equal(formatPercent(null), "-");
});

test("the report has a header, one line per student, and the summary", () => {
  assert.equal(
    renderReport([ADA]),
    [
      "student name             homework  quizzes  project    exams    final  letter",
      "s01     Ada Lovelace         95.0     87.5     92.0     90.5     91.6  A-",
      "",
      "students: 1",
      "mean: 91.6",
      "median: 91.6",
      "letters: A- 1",
      "",
    ].join("\n"),
  );
});

test("an empty class still prints the summary", () => {
  const text = renderReport([]);
  assert.match(text, /students: 0\n/);
  assert.match(text, /letters: -\n$/);
});
