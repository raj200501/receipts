import assert from "node:assert/strict";
import { test } from "node:test";
import { formatCsv, formatField, formatRow, needsQuotes } from "../src/format.ts";

test("plain values are written as they are", () => {
  assert.equal(formatRow(["7", "Ada Lovelace", "London"]), "7,Ada Lovelace,London");
});

test("values with the delimiter or a line break are quoted", () => {
  assert.equal(formatField("Hopper, Grace"), '"Hopper, Grace"');
  assert.equal(formatField("first\nsecond"), '"first\nsecond"');
  assert.equal(formatField("a;b", ";"), '"a;b"');
});

test("values that start or end with a space are quoted", () => {
  assert.equal(formatField(" spaced "), '" spaced "');
  assert.equal(needsQuotes("inner space"), false);
});

test("which values need quotes", () => {
  assert.equal(needsQuotes("plain"), false);
  assert.equal(needsQuotes('5" floppy'), true);
  assert.equal(needsQuotes("tab\there", "\t"), true);
});

test("a record with one empty field is not written as a blank line", () => {
  assert.equal(formatRow([""]), '""');
  assert.equal(formatRow(["", ""]), ",");
});

test("formatCsv ends every record with the line ending", () => {
  const rows = [
    ["id", "name"],
    ["7", "Ada"],
  ];
  assert.equal(formatCsv(rows), "id,name\n7,Ada\n");
  assert.equal(formatCsv(rows, { lineEnding: "\r\n" }), "id,name\r\n7,Ada\r\n");
  assert.equal(formatCsv(rows, { delimiter: "\t" }), "id\tname\n7\tAda\n");
});
