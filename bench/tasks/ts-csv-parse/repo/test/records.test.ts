import assert from "node:assert/strict";
import { test } from "node:test";
import { readRows } from "../src/parse.ts";
import { toTable } from "../src/records.ts";

test("records are keyed by the header names", () => {
  const table = toTable(readRows("id,name\n7,Ada\n8,Grace\n"));
  assert.deepEqual(table.columns, ["id", "name"]);
  assert.deepEqual(table.records, [
    { id: "7", name: "Ada" },
    { id: "8", name: "Grace" },
  ]);
});

test("a record with the wrong number of fields names its line", () => {
  assert.throws(() => toTable(readRows("id,name\n7,Ada\n\n8\n")), {
    name: "CsvError",
    message: "line 4: expected 2 fields, got 1",
  });
});

test("header names must not repeat", () => {
  assert.throws(() => toTable(readRows("id,name,id\n1,2,3\n")), /column name "id" appears twice/);
});

test("every column needs a name", () => {
  assert.throws(() => toTable(readRows("id,,city\n1,2,3\n")), /line 1: column 2 has no name/);
});

test("empty input has no columns and no records", () => {
  assert.deepEqual(toTable(readRows("")), { columns: [], records: [] });
});
