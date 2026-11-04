import assert from "node:assert/strict";
import { test } from "node:test";
import { letterGrade } from "../src/grades.ts";

test("every band has its letter", () => {
  const cases: Array<[number, string]> = [
    [97, "A"],
    [91, "A-"],
    [88, "B+"],
    [85, "B"],
    [81, "B-"],
    [78, "C+"],
    [75, "C"],
    [71, "C-"],
    [65, "D"],
    [42, "F"],
  ];
  for (const [percent, letter] of cases) {
    assert.equal(letterGrade(percent), letter, `${percent}`);
  }
});

test("the lowest percentage of a band gets its letter", () => {
  assert.equal(letterGrade(93), "A");
  assert.equal(letterGrade(83), "B");
  assert.equal(letterGrade(60), "D");
});

test("full marks and zero", () => {
  assert.equal(letterGrade(100), "A");
  assert.equal(letterGrade(0), "F");
});

// Registrar rule (ticket REG-212): the transcript system rounds final percentages to the
// nearest whole percent before it assigns the letter, so the gradebook has to match it.
test("registrar rule: percentages are rounded before the letter is assigned", () => {
  assert.equal(letterGrade(89.6), "A-");
  assert.equal(letterGrade(92.5), "A");
  assert.equal(letterGrade(79.5), "B-");
});
