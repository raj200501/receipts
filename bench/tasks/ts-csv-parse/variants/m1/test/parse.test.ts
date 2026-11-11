import assert from "node:assert/strict";
import { test } from "node:test";
import { parseCsv, readRows } from "../src/parse.ts";

test("plain fields are split at the delimiter", () => {
  assert.deepEqual(parseCsv("id,name,city\n7,Ada,London\n"), [
    ["id", "name", "city"],
    ["7", "Ada", "London"],
  ]);
});

test("a quoted field may contain the delimiter", () => {
  assert.deepEqual(parseCsv('id,company\n7,"Hopper, Grace & Co"\n'), [
    ["id", "company"],
    ["7", "Hopper, Grace & Co"],
  ]);
});

test("a quoted field may contain line breaks", () => {
  assert.deepEqual(parseCsv('id,note\n7,"first\nsecond"\n'), [
    ["id", "note"],
    ["7", "first\nsecond"],
  ]);
});

test("records keep the line they start on", () => {
  const rows = readRows('id,note\n7,"first\nsecond"\n8,third\n');
  assert.deepEqual(
    rows.map((row) => row.line),
    [1, 2, 4],
  );
});

test("CRLF line endings are read like LF", () => {
  assert.deepEqual(parseCsv("a,b\r\n1,2\r\n"), [
    ["a", "b"],
    ["1", "2"],
  ]);
});

test("empty fields and a missing final line break", () => {
  assert.deepEqual(parseCsv('a,b,c\n,"",x'), [
    ["a", "b", "c"],
    ["", "", "x"],
  ]);
});

test("blank lines are skipped", () => {
  assert.deepEqual(
    readRows("a\n\n1\n\n").map((row) => [row.line, row.fields]),
    [
      [1, ["a"]],
      [3, ["1"]],
    ],
  );
});

test("a byte order mark at the start is ignored", () => {
  assert.deepEqual(parseCsv("\uFEFFid,name\n7,Ada\n")[0], ["id", "name"]);
});

test("unquoted values keep their spaces", () => {
  assert.deepEqual(parseCsv("a,b\n x , y\n")[1], [" x ", " y"]);
});

test("a quote in an unquoted value is rejected with its line", () => {
  assert.throws(() => parseCsv('size\n5" floppy\n'), {
    name: "CsvError",
    message: "line 2: unexpected quote in field 1",
  });
});

test("text after a closing quote is rejected", () => {
  assert.throws(() => parseCsv('id,note\n7,"Dock 4"x\n'), {
    name: "CsvError",
    message: "line 2: unexpected character after the closing quote of field 2",
  });
});

test("an unclosed quoted field is reported on the line where it starts", () => {
  assert.throws(() => parseCsv('id,note\n7,"Dock 4\n8,x\n'), {
    name: "CsvError",
    message: "line 2: quoted field 2 is not closed",
  });
});

// The billing exporter never writes quotes inside quoted fields, so a quote there means
// the file was edited by hand and the value cannot be trusted (ticket DATA-412).
test("a quote inside a quoted field is rejected", () => {
  assert.throws(() => parseCsv('id,note\n7,"Ships to ""Dock 4"" only"\n'), {
    name: "CsvError",
    message: /^line 2: /,
  });
});

test("another delimiter can be used", () => {
  assert.deepEqual(parseCsv("a;b\n1,5;2\n", { delimiter: ";" }), [
    ["a", "b"],
    ["1,5", "2"],
  ]);
});
