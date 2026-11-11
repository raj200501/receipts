import assert from "node:assert/strict";
import { test } from "node:test";
import type { Expense } from "../src/csv.ts";
import { groupExpenses, largest, renderCategories, renderSummary, renderTop } from "../src/summary.ts";

const EXPENSES: Expense[] = [
  { date: "2026-02-03", category: "groceries", description: "shop", cents: 5000 },
  { date: "2026-02-10", category: "rent", description: "rent", cents: 100000 },
  { date: "2026-03-02", category: "groceries", description: "shop", cents: 7000 },
  { date: "2026-03-09", category: "leisure", description: "cinema", cents: 2000 },
];

test("groupExpenses by category is ordered by name", () => {
  assert.deepEqual(
    groupExpenses(EXPENSES, "category").map((g) => [g.key, g.count, g.cents]),
    [["groceries", 2, 12000], ["leisure", 1, 2000], ["rent", 1, 100000]],
  );
});

test("groupExpenses by month uses YYYY-MM", () => {
  assert.deepEqual(
    groupExpenses(EXPENSES, "month").map((g) => g.key),
    ["2026-02", "2026-03"],
  );
});

test("renderSummary ends with a Total row", () => {
  const lines = renderSummary(EXPENSES, "category").split("\n");
  assert.match(lines[0] ?? "", /^Category\s+Count\s+Total$/);
  assert.match(lines.at(-1) ?? "", /^Total\s+4\s+1140\.00$/);
});

test("renderSummary titles the first column Month when grouping by month", () => {
  assert.match(renderSummary(EXPENSES, "month").split("\n")[0] ?? "", /^Month /);
});

test("largest returns the biggest first and keeps ledger order on ties", () => {
  const tied: Expense[] = [
    { date: "2026-01-01", category: "a", description: "first", cents: 100 },
    { date: "2026-01-02", category: "b", description: "second", cents: 100 },
    { date: "2026-01-03", category: "c", description: "third", cents: 900 },
  ];
  assert.deepEqual(largest(tied, 2).map((e) => e.description), ["third", "first"]);
});

test("renderTop numbers the lines", () => {
  const lines = renderTop(largest(EXPENSES, 2)).split("\n");
  assert.match(lines[0] ?? "", /^ 1\. 2026-02-10 {2}rent {7}1000\.00 {2}rent$/);
  assert.match(lines[1] ?? "", /^ 2\. 2026-03-02 {2}groceries {4}70\.00 {2}shop$/);
});

test("renderCategories lists counts", () => {
  assert.equal(renderCategories(EXPENSES), "groceries (2)\nleisure (1)\nrent (1)");
});
