import assert from "node:assert/strict";
import { test } from "node:test";
import { readJsonLines, recordLine, tableRows } from "../src/jsonl.ts";

test("a record becomes one line of JSON in column order", () => {
  assert.equal(recordLine({ id: "7", name: "Ada" }), '{"id":"7","name":"Ada"}');
});

test("columns are the keys in the order they first appear", () => {
  const table = readJsonLines('{"id":1,"name":"Ada"}\n\n{"id":2,"city":"Oslo"}\n');
  assert.deepEqual(table.columns, ["id", "name", "city"]);
  assert.deepEqual(table.records, [
    { id: "1", name: "Ada", city: "" },
    { id: "2", name: "", city: "Oslo" },
  ]);
});

test("numbers, booleans, and null become field text", () => {
  const table = readJsonLines('{"n":2.5,"ok":false,"none":null}\n');
  assert.deepEqual(tableRows(table), [
    ["n", "ok", "none"],
    ["2.5", "false", ""],
  ]);
});

test("a line that is not a JSON object names its line", () => {
  assert.throws(() => readJsonLines('{"id":1}\n[1,2]\n'), /line 2: expected a JSON object/);
  assert.throws(() => readJsonLines('{"id":1}\n{"id":\n'), /line 2: not valid JSON/);
  assert.throws(() => readJsonLines('{"tags":["a"]}\n'), /line 1: "tags" is not a string/);
});
