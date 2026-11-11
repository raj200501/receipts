import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { main } from "../src/cli.ts";

function setup(): (argv: string[]) => { status: number; out: string; err: string } {
  const file = join(mkdtempSync(join(tmpdir(), "todo-cli-")), "todos.json");
  return (argv) => {
    let out = "";
    let err = "";
    const status = main([...argv, "--file", file], {
      out: (text) => {
        out += text;
      },
      err: (text) => {
        err += text;
      },
      today: () => "2026-11-02",
    });
    return { status, out, err };
  };
}

test("add prints the new number and list shows the item", () => {
  const todo = setup();
  assert.deepEqual(todo(["add", "Write", "the", "report", "--due", "2026-11-12"]), {
    status: 0,
    out: "Added #1: Write the report\n",
    err: "",
  });
  assert.equal(todo(["list"]).out, "[ ]   1  Write the report  (due 2026-11-12)\n");
});

test("list says so when the list is empty", () => {
  assert.equal(setup()(["list"]).out, "No todos.\n");
});

test("list keeps the order of the file and --open hides finished items", () => {
  const todo = setup();
  todo(["add", "first"]);
  todo(["add", "second"]);
  todo(["done", "1"]);
  assert.equal(todo(["list"]).out, "[x]   1  first\n[ ]   2  second\n");
  assert.equal(todo(["list", "--open"]).out, "[ ]   2  second\n");
});

test("done and rm confirm with the number", () => {
  const todo = setup();
  todo(["add", "first"]);
  assert.equal(todo(["done", "1"]).out, "Completed #1\n");
  assert.equal(todo(["rm", "1"]).out, "Removed #1\n");
  assert.equal(todo(["list"]).out, "No todos.\n");
});

test("done on a number that does not exist exits with status 1", () => {
  const result = setup()(["done", "9"]);
  assert.equal(result.status, 1);
  assert.equal(result.err, "todo: no todo with number 9\n");
});

test("a due day that is not a real day exits with status 2", () => {
  const result = setup()(["add", "x", "--due", "2026-02-30"]);
  assert.equal(result.status, 2);
  assert.match(result.err, /^todo: .*YYYY-MM-DD/);
});

test("an unknown command or option exits with status 2", () => {
  const todo = setup();
  assert.equal(todo(["frobnicate"]).status, 2);
  assert.equal(todo(["list", "--colour"]).status, 2);
});

test("a todo number must be a number", () => {
  const result = setup()(["rm", "first"]);
  assert.equal(result.status, 2);
  assert.equal(result.err, 'todo: "first" is not a todo number\n');
});

test("help prints the usage and exits with status 0", () => {
  const result = setup()(["help"]);
  assert.equal(result.status, 0);
  assert.match(result.out, /^usage: todo/);
});
