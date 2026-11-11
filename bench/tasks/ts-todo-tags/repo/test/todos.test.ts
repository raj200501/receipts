import assert from "node:assert/strict";
import { test } from "node:test";
import { addTodo, completeTodo, findTodo, removeTodo, TodoError } from "../src/todos.ts";
import { emptyStore } from "../src/store.ts";

test("addTodo numbers items from the file's nextId", () => {
  const file = emptyStore();
  const first = addTodo(file, "Write the report", {}, "2026-11-02");
  const second = addTodo(file, "Book the room", { due: "2026-11-09" }, "2026-11-02");
  assert.equal(first.id, 1);
  assert.equal(second.id, 2);
  assert.equal(second.due, "2026-11-09");
  assert.equal(file.nextId, 3);
});

test("addTodo trims the title and records the day it was added", () => {
  const todo = addTodo(emptyStore(), "  Water plants  ", {}, "2026-11-03");
  assert.equal(todo.title, "Water plants");
  assert.equal(todo.created, "2026-11-03");
  assert.equal(todo.done, false);
  assert.equal(todo.due, null);
});

test("addTodo rejects an empty title", () => {
  assert.throws(() => addTodo(emptyStore(), "   ", {}, "2026-11-03"), TodoError);
});

test("addTodo rejects a due day that is not a real day", () => {
  assert.throws(
    () => addTodo(emptyStore(), "x", { due: "2026-02-30" }, "2026-11-03"),
    /not a day in the form YYYY-MM-DD/,
  );
});

test("completeTodo marks the item done", () => {
  const file = emptyStore();
  addTodo(file, "x", {}, "2026-11-03");
  assert.equal(completeTodo(file, 1).done, true);
  assert.equal(findTodo(file, 1).done, true);
});

test("removeTodo takes the item off the list and never reuses its id", () => {
  const file = emptyStore();
  addTodo(file, "a", {}, "2026-11-03");
  addTodo(file, "b", {}, "2026-11-03");
  removeTodo(file, 1);
  assert.deepEqual(
    file.todos.map((todo) => todo.id),
    [2],
  );
  assert.equal(addTodo(file, "c", {}, "2026-11-03").id, 3);
});

test("findTodo reports a missing item as not-found", () => {
  assert.throws(
    () => findTodo(emptyStore(), 7),
    (error: unknown) => error instanceof TodoError && error.code === "not-found",
  );
});
