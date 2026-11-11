import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { main } from "../src/cli.ts";

function setup() {
  const file = join(mkdtempSync(join(tmpdir(), "todo-tags-")), "todos.json");
  const run = (argv: string[]) => {
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
  return { file, run };
}

test("add --tag stores normalized tags and list shows them", () => {
  const { file, run } = setup();
  assert.equal(run(["add", "Rotate", "keys", "--tag", "Ops", "--tag", "auth", "--tag", "ops"]).status, 0);
  assert.deepEqual(JSON.parse(readFileSync(file, "utf8")).todos[0].tags, ["ops", "auth"]);
  assert.equal(run(["list"]).out, "[ ]   1  Rotate keys  #ops #auth\n");
});

test("add rejects a malformed tag and stores nothing", () => {
  const { run } = setup();
  const result = run(["add", "x", "--tag", "two words"]);
  assert.equal(result.status, 2);
  assert.equal(run(["list"]).out, "No todos.\n");
});

test("list --tag keeps items with every given tag", () => {
  const { run } = setup();
  run(["add", "one", "--tag", "api", "--tag", "auth"]);
  run(["add", "two", "--tag", "api"]);
  run(["add", "three"]);
  assert.equal(run(["list", "--tag", "api"]).out.split("\n").filter(Boolean).length, 2);
  assert.equal(run(["list", "--tag", "API", "--tag", "auth"]).out, "[ ]   1  one  #api #auth\n");
  assert.equal(run(["list", "--tag", "docs"]).out, "No todos.\n");
});

test("list --sort title and due order the output", () => {
  const { run } = setup();
  run(["add", "beta", "--due", "2026-11-09"]);
  run(["add", "Alpha"]);
  run(["add", "gamma", "--due", "2026-11-05"]);
  const numbers = (text: string) => text.split("\n").filter(Boolean).map((line) => line.slice(4, 7).trim());
  assert.deepEqual(numbers(run(["list", "--sort", "title"]).out), ["2", "1", "3"]);
  assert.deepEqual(numbers(run(["list", "--sort", "due"]).out), ["3", "1", "2"]);
});

test("list --sort with an unknown key exits with status 2", () => {
  assert.equal(setup().run(["list", "--sort", "colour"]).status, 2);
});
