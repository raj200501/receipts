/** Operations on the items of a todo file. */

import { isValidDay } from "./dates.ts";
import type { Todo, TodoFile } from "./types.ts";

/** Thrown for a request the list cannot carry out. */
export class TodoError extends Error {
  readonly code: "not-found" | "invalid";

  constructor(code: "not-found" | "invalid", message: string) {
    super(message);
    this.name = "TodoError";
    this.code = code;
  }
}

/** What `addTodo` accepts besides the title. */
export interface AddOptions {
  due?: string | null;
  /** Already normalized tags (see tags.ts). */
  tags?: readonly string[];
}

/** Add an item at the end of the list and return it. */
export function addTodo(file: TodoFile, title: string, options: AddOptions, today: string): Todo {
  const trimmed = title.trim();
  if (trimmed === "") {
    throw new TodoError("invalid", "a todo needs a title");
  }
  const due = options.due ?? null;
  if (due !== null && !isValidDay(due)) {
    throw new TodoError("invalid", `"${due}" is not a day in the form YYYY-MM-DD`);
  }
  const todo: Todo = { id: file.nextId, title: trimmed, done: false, due, created: today };
  if (options.tags !== undefined && options.tags.length > 0) {
    todo.tags = [...options.tags];
  }
  file.todos.push(todo);
  file.nextId += 1;
  return todo;
}

/** The item with this id. */
export function findTodo(file: TodoFile, id: number): Todo {
  const todo = file.todos.find((item) => item.id === id);
  if (todo === undefined) {
    throw new TodoError("not-found", `no todo with number ${id}`);
  }
  return todo;
}

/** Mark an item done and return it. */
export function completeTodo(file: TodoFile, id: number): Todo {
  const todo = findTodo(file, id);
  todo.done = true;
  return todo;
}

/** Take an item off the list and return it. */
export function removeTodo(file: TodoFile, id: number): Todo {
  const todo = findTodo(file, id);
  file.todos = file.todos.filter((item) => item.id !== id);
  return todo;
}
