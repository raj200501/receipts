import assert from "node:assert/strict";
import { test } from "node:test";
import { formatCents, padLeft, padRight, renderTable } from "../src/format.ts";

test("formatCents prints two places", () => {
  assert.equal(formatCents(123456), "1234.56");
  assert.equal(formatCents(5), "0.05");
  assert.equal(formatCents(0), "0.00");
});

test("formatCents keeps the sign of refunds", () => {
  assert.equal(formatCents(-250), "-2.50");
});

test("padding helpers do not truncate", () => {
  assert.equal(padRight("ab", 4), "ab  ");
  assert.equal(padLeft("ab", 4), "  ab");
  assert.equal(padLeft("abcdef", 4), "abcdef");
});

test("renderTable aligns the first column left and the others right", () => {
  const table = renderTable(["Name", "N"], [["alpha", "3"], ["b", "12"]]);
  assert.equal(table, "Name    N\nalpha   3\nb      12");
});
