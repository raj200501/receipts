import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { main } from "../src/cli.ts";
import { formatCsv, formatField } from "../src/format.ts";
import { parseCsv, readRows } from "../src/parse.ts";

test("a doubled quote inside a quoted field is one quote", () => {
  assert.deepEqual(parseCsv('id,note\nC-1042,"Ships to ""Dock 4"" only"\n')[1], [
    "C-1042",
    'Ships to "Dock 4" only',
  ]);
});

test("doubled quotes at the start and the end of a value", () => {
  assert.deepEqual(parseCsv('a,b,c\n"""Fragile""","x ""y""",""""\n')[1], [
    '"Fragile"',
    'x "y"',
    '"',
  ]);
});

test("doubled quotes next to delimiters and line breaks", () => {
  const rows = readRows('id,note\n7,"say ""yes"", then\n""no"""\n8,x\n');
  assert.deepEqual(rows[1], { line: 2, fields: ["7", 'say "yes", then\n"no"'] });
  assert.equal(rows[2].line, 4);
});

test("a quote after a doubled quote still has to close the field", () => {
  assert.throws(() => parseCsv('note\n"Dock ""4""x\n'), /quoted field 1 is not closed/);
  assert.throws(() => parseCsv('note\n"Dock ""4"" x"y\n'), /after the closing quote/);
});

test("the writer doubles quotes inside quoted values", () => {
  assert.equal(formatField('Ships to "Dock 4" only'), '"Ships to ""Dock 4"" only"');
  assert.equal(formatField('"'), '""""');
});

test("written values with quotes read back the same", () => {
  const rows = [
    ["id", "note"],
    ["7", 'Ships to "Dock 4" only'],
    ["8", '"Fragile", top\nshelf'],
  ];
  assert.deepEqual(parseCsv(formatCsv(rows)), rows);
  assert.deepEqual(parseCsv(formatCsv(rows, { delimiter: ";" }), { delimiter: ";" }), rows);
});

test("csvtool json and csvtool csv handle quotes in values", () => {
  const dir = mkdtempSync(join(tmpdir(), "csvtool-quotes-"));
  const csv = join(dir, "export.csv");
  writeFileSync(csv, 'id,note\nC-1042,"Ships to ""Dock 4"" only"\n');
  let out = "";
  const output = {
    out: (text: string) => {
      out += text;
    },
    err: () => {},
  };
  assert.equal(main(["json", csv], output), 0);
  assert.equal(out, '{"id":"C-1042","note":"Ships to \\"Dock 4\\" only"}\n');
  const jsonl = join(dir, "records.jsonl");
  writeFileSync(jsonl, out);
  out = "";
  assert.equal(main(["csv", jsonl], output), 0);
  assert.equal(out, 'id,note\nC-1042,"Ships to ""Dock 4"" only"\n');
});
