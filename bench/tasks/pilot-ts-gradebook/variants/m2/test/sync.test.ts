import assert from "node:assert/strict";
import { test } from "node:test";
import { gradeStudents } from "../src/grades.ts";
import { parseScores } from "../src/scores.ts";
import { pushGrades, syncPayload } from "../src/sync.ts";

const SCORES = `student,name,assignment,category,points,max_points
s01,Ada Lovelace,hw1,homework,9,10
s01,Ada Lovelace,q1,quizzes,19,20
s01,Ada Lovelace,project,project,47,50
s01,Ada Lovelace,midterm,exams,95,100
s02,Grace Hopper,hw1,homework,7,10
s02,Grace Hopper,q1,quizzes,15,20
s02,Grace Hopper,project,project,40,50
s02,Grace Hopper,midterm,exams,75,100
`;

function payload() {
  return syncPayload("CS101", gradeStudents(parseScores(SCORES)));
}

test("sync payload names the course", () => {
  assert.equal(payload().course, "CS101");
});

test("sync payload lists every student once", () => {
  assert.deepEqual(
    payload().grades.map((grade) => grade.student),
    ["s01", "s02"],
  );
});

test("sync payload keeps one decimal place and the letter", () => {
  const [ada] = payload().grades;
  assert.equal(ada.percent, 93.3);
  assert.equal(ada.letter, "A");
});

test("pushes final grades to the LMS", async () => {
  // Needs the LMS sync daemon (/run/lms/sync.sock), which runs only on the school's servers.
  assert.equal(await pushGrades(payload()), "ok");
});
