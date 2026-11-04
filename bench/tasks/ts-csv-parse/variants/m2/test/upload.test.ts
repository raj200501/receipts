import assert from "node:assert/strict";
import { test } from "node:test";
import { readRows } from "../src/parse.ts";
import { toTable } from "../src/records.ts";
import { toBatches, uploadBatch } from "../src/upload.ts";

const CONTACTS = toTable(
  readRows("id,name\n1,Ada\n2,Grace\n3,Alan\n4,Edsger\n5,Barbara\n"),
).records;

test("records are split into batches of the given size", () => {
  assert.deepEqual(
    toBatches("contacts", CONTACTS, 2).map((batch) => batch.records.length),
    [2, 2, 1],
  );
});

test("batches are numbered from 1 and name their table", () => {
  assert.deepEqual(
    toBatches("contacts", CONTACTS, 2).map((batch) => [batch.table, batch.sequence]),
    [
      ["contacts", 1],
      ["contacts", 2],
      ["contacts", 3],
    ],
  );
});

test("one batch holds every record up to the default size", () => {
  const [batch, ...rest] = toBatches("contacts", CONTACTS);
  assert.equal(batch.records.length, 5);
  assert.deepEqual(rest, []);
});

test("a batch size below 1 is rejected", () => {
  assert.throws(() => toBatches("contacts", CONTACTS, 0), RangeError);
});

test("uploads a batch to the warehouse", async () => {
  // Needs the WAREHOUSE_TOKEN secret, which only the release pipeline has.
  const [batch] = toBatches("contacts", CONTACTS);
  assert.equal(await uploadBatch(batch), 201);
});
