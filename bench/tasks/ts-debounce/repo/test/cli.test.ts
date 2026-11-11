import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { main } from "../src/cli.ts";

const dir = mkdtempSync(join(tmpdir(), "autosave-sim-"));
let logs = 0;

after(() => rmSync(dir, { recursive: true, force: true }));

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

function log(...lines: string[]): string {
  logs += 1;
  const path = join(dir, `keys-${logs}.txt`);
  writeFileSync(path, `${lines.join("\n")}\n`);
  return path;
}

test("autosave-sim prints the report", () => {
  const path = log("0 type Hi", "3000 type Hi there");
  assert.deepEqual(run(["--wait", "500", path]), {
    status: 0,
    out: 'autosave of body (wait 500 ms)\n   500 ms  saved r1 "Hi"\n  3500 ms  saved r2 "Hi there"\n2 edits, 2 saves\n',
    err: "",
  });
});

test("the field and the max wait appear in the report", () => {
  const path = log("100 type x");
  const { status, out } = run(["--field", "checklist", "--wait", "700", "--max-wait", "4000", path]);
  assert.equal(status, 0);
  assert.equal(out.split("\n")[0], "autosave of checklist (wait 700 ms, max wait 4000 ms)");
});

test("a bad log line exits with status 2 and names the line", () => {
  const path = log("0 type a", "# fine", "soon type b");
  assert.deepEqual(run([path]), {
    status: 2,
    out: "",
    err: 'autosave-sim: line 3: expected "TIME type TEXT" or "TIME close", got "soon type b"\n',
  });
});

test("a file that cannot be read exits with status 2", () => {
  const { status, err } = run([join(dir, "missing.txt")]);
  assert.equal(status, 2);
  assert.match(err, /^autosave-sim: cannot read /);
});

test("anything else prints the usage", () => {
  for (const argv of [[], ["--field", "footer", "x.txt"], ["--max-wait", "100", "x.txt"], ["--speed", "x.txt"]]) {
    const { status, err } = run(argv);
    assert.equal(status, 2, argv.join(" "));
    assert.match(err, /^usage: autosave-sim /);
  }
  assert.match(run(["--wait", "soon", "x.txt"]).err, /--wait must be a whole number of milliseconds/);
});
