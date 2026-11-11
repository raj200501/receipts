import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { emptyStore, loadStore, saveStore, StoreError, validateStore } from "../src/store.ts";

function tempFile(): string {
  return join(mkdtempSync(join(tmpdir(), "todo-store-")), "todos.json");
}

test("loadStore treats a missing file as an empty list", () => {
  assert.deepEqual(loadStore(tempFile()), emptyStore());
});

test("saveStore and loadStore round-trip", () => {
  const path = tempFile();
  const file = {
    nextId: 3,
    todos: [{ id: 2, title: "Book the room", done: true, due: null, created: "2026-11-02" }],
  };
  saveStore(path, file);
  assert.deepEqual(loadStore(path), file);
});

test("loadStore reports a file that is not JSON", () => {
  const path = tempFile();
  writeFileSync(path, "{not json");
  assert.throws(() => loadStore(path), StoreError);
});

test("validateStore names the item that is wrong", () => {
  const raw = { nextId: 2, todos: [{ id: 1, title: "x", done: "no", due: null, created: "d" }] };
  assert.throws(() => validateStore(raw, "f.json"), /f\.json: item 1 has no done flag/);
});

test("validateStore requires nextId and a todos list", () => {
  assert.throws(() => validateStore({ todos: [] }, "f.json"), /expected nextId/);
});
