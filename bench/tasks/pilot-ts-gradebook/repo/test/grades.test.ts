import assert from "node:assert/strict";
import { test } from "node:test";
import { categoryPercent, finalPercent, gradeStudents } from "../src/grades.ts";
import { parseScores } from "../src/scores.ts";

const ROWS = `student,name,assignment,category,points,max_points
s02,Grace Hopper,hw1,homework,8,10
s02,Grace Hopper,q1,quizzes,15,20
s02,Grace Hopper,project,project,41,50
s02,Grace Hopper,midterm,exams,81,100
s01,Ada Lovelace,hw1,homework,9,10
s01,Ada Lovelace,hw2,homework,10,10
s01,Ada Lovelace,q1,quizzes,18,20
s01,Ada Lovelace,project,project,46,50
s01,Ada Lovelace,midterm,exams,90,100
`;

test("category percentage is points earned over points possible", () => {
  const rows = parseScores(ROWS).filter((row) => row.student === "s01");
  assert.equal(categoryPercent(rows.filter((row) => row.category === "homework")), 95);
});

test("missing work counts as zero points", () => {
  const rows = parseScores(
    "student,name,assignment,category,points,max_points\ns01,Ada,hw1,homework,10,10\ns01,Ada,hw2,homework,,10\n",
  );
  assert.equal(categoryPercent(rows), 50);
});

test("a category without rows has no percentage", () => {
  assert.equal(categoryPercent([]), null);
});

test("final percentage weights the categories", () => {
  const percent = finalPercent({ homework: 90, quizzes: 80, project: 100, exams: 70 });
  assert.ok(Math.abs(percent - 84) < 1e-9, String(percent));
});

test("students are graded in id order", () => {
  const results = gradeStudents(parseScores(ROWS));
  assert.deepEqual(
    results.map((result) => result.student),
    ["s01", "s02"],
  );
  assert.equal(results[1].name, "Grace Hopper");
});

test("each result carries the letter of its final percentage", () => {
  const [ada] = gradeStudents(parseScores(ROWS));
  assert.equal(ada.letter, "A-");
  assert.ok(Math.abs(ada.percent - 91.9) < 1e-9, String(ada.percent));
});
