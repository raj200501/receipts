import assert from "node:assert/strict";
import { test } from "node:test";
import { formatProblems, summaryLine } from "../src/format.ts";

test("formatProblems prints file:line: rule: message", () => {
  const text = formatProblems("CHANGELOG.md", [{ line: 12, rule: "date-format", message: "needs a date" }]);
  assert.equal(text, "CHANGELOG.md:12: date-format: needs a date");
});

test("summaryLine uses the right plural", () => {
  assert.equal(summaryLine(0), "no problems found");
  assert.equal(summaryLine(1), "1 problem found");
  assert.equal(summaryLine(3), "3 problems found");
});
