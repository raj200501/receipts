import assert from "node:assert/strict";
import { test } from "node:test";
import { formatList, formatTodo } from "../src/format.ts";

const OPEN = { id: 1, title: "Write the report", done: false, due: "2026-11-12", created: "x" };
const DONE = { id: 12, title: "Book the room", done: true, due: null, created: "x" };

test("formatTodo shows the box, the number, the title, and the due day", () => {
  assert.equal(formatTodo(OPEN), "[ ]   1  Write the report  (due 2026-11-12)");
});

test("formatTodo marks finished items and leaves out a missing due day", () => {
  assert.equal(formatTodo(DONE), "[x]  12  Book the room");
});

test("formatList prints one line per item", () => {
  assert.equal(formatList([OPEN, DONE]), `${formatTodo(OPEN)}\n${formatTodo(DONE)}\n`);
});

test("formatList says so when there is nothing to show", () => {
  assert.equal(formatList([]), "No todos.\n");
});
