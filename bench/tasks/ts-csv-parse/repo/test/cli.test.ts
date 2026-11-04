import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { main } from "../src/cli.ts";

function run(argv: string[]): { status: number; out: string; err: string } {
  let out = "";
  let err = "";
  const status = main(argv, {
    out: (text) => {
      out += text;
    },
    err: (text) => {
      err += text;
    },
  });
  return { status, out, err };
}

function inputFile(name: string, text: string): string {
  const path = join(mkdtempSync(join(tmpdir(), "csvtool-")), name);
  writeFileSync(path, text);
  return path;
}

test("json prints one object per record", () => {
  const path = inputFile("contacts.csv", 'id,name\n7,"Lovelace, Ada"\n8,Grace\n');
  const { status, out } = run(["json", path]);
  assert.equal(status, 0);
  assert.equal(out, '{"id":"7","name":"Lovelace, Ada"}\n{"id":"8","name":"Grace"}\n');
});

test("columns lists the header and counts the records", () => {
  const path = inputFile("contacts.csv", "id,name,city\n7,Ada,London\n");
  const { status, out } = run(["columns", path]);
  assert.equal(status, 0);
  assert.equal(out, "1  id\n2  name\n3  city\n3 columns, 1 record\n");
});

test("csv writes JSON lines as CSV", () => {
  const path = inputFile("records.jsonl", '{"id":7,"name":"Lovelace, Ada"}\n{"id":8}\n');
  const { status, out } = run(["csv", path]);
  assert.equal(status, 0);
  assert.equal(out, 'id,name\n7,"Lovelace, Ada"\n8,\n');
});

test("the delimiter option applies to reading", () => {
  const path = inputFile("finance.csv", "id;amount\n7;12,50\n");
  const { out } = run(["json", "--delimiter", ";", path]);
  assert.equal(out, '{"id":"7","amount":"12,50"}\n');
});

test("a broken row stops the command with status 2", () => {
  const path = inputFile("contacts.csv", "id,name\n7,Ada\n8\n");
  const { status, out, err } = run(["json", path]);
  assert.equal(status, 2);
  assert.equal(out, "");
  assert.equal(err, "csvtool: line 3: expected 2 fields, got 1\n");
});

test("a file that cannot be read stops the command with status 2", () => {
  const { status, err } = run(["json", join(tmpdir(), "does-not-exist", "x.csv")]);
  assert.equal(status, 2);
  assert.match(err, /^csvtool: cannot read /);
});

test("wrong arguments print the usage", () => {
  const { status, err } = run(["select", "x.csv"]);
  assert.equal(status, 2);
  assert.match(err, /^usage: csvtool json FILE/);
});
