import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { main } from "../src/cli.ts";

const dir = mkdtempSync(join(tmpdir(), "vercmp-"));
let files = 0;

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

function versionsFile(...versions: string[]): string {
  files += 1;
  const path = join(dir, `tags-${files}.txt`);
  writeFileSync(path, `${versions.join("\n")}\n`);
  return path;
}

test("compare prints -1, 0, or 1", () => {
  assert.deepEqual(run(["compare", "2.7.1", "2.10.0"]), { status: 0, out: "-1\n", err: "" });
  assert.equal(run(["compare", "v2.7.1", "2.7.1"]).out, "0\n");
  assert.equal(run(["compare", "3.0.0", "2.99.0"]).out, "1\n");
});

test("sort prints the versions from lowest to highest as written", () => {
  const path = versionsFile("v2.10.0", "v2.7.1", "# old", "v1.12.0", "v2.9.3");
  assert.deepEqual(run(["sort", path]), {
    status: 0,
    out: "v1.12.0\nv2.7.1\nv2.9.3\nv2.10.0\n",
    err: "",
  });
});

test("sort --reverse prints the highest version first", () => {
  const path = versionsFile("2.7.1", "2.10.0", "2.9.3");
  assert.equal(run(["sort", "--reverse", path]).out, "2.10.0\n2.9.3\n2.7.1\n");
});

test("latest prints the highest release and skips prereleases", () => {
  const path = versionsFile("v2.7.1", "v2.8.0-rc.1", "v2.6.4");
  assert.deepEqual(run(["latest", path]), { status: 0, out: "v2.7.1\n", err: "" });
  assert.equal(run(["latest", "--pre", path]).out, "v2.8.0-rc.1\n");
});

test("latest exits with status 1 when the file has no release", () => {
  const path = versionsFile("v2.8.0-rc.1");
  const { status, out, err } = run(["latest", path]);
  assert.equal(status, 1);
  assert.equal(out, "");
  assert.equal(err, `vercmp: no release in ${path}\n`);
});

test("bump prints the next version", () => {
  assert.equal(run(["bump", "minor", "v2.7.1"]).out, "v2.8.0\n");
  assert.equal(run(["bump", "pre", "2.8.0-beta.2", "--preid", "rc"]).out, "2.8.0-rc.1\n");
});

test("a bad version exits with status 2 and names the line", () => {
  const path = versionsFile("v2.7.0", "v2.8", "v2.9.0");
  assert.deepEqual(run(["sort", path]), {
    status: 2,
    out: "",
    err: 'vercmp: line 2: not a version: "v2.8"\n',
  });
});

test("a file that cannot be read exits with status 2", () => {
  const { status, err } = run(["latest", join(dir, "missing.txt")]);
  assert.equal(status, 2);
  assert.match(err, /^vercmp: cannot read /);
});

test("anything else prints the usage", () => {
  for (const argv of [[], ["list"], ["sort"], ["sort", "--newest", "tags.txt"], ["bump", "huge", "1.0.0"]]) {
    const { status, err } = run(argv);
    assert.equal(status, 2, argv.join(" "));
    assert.match(err, /^usage: vercmp compare A B/);
  }
});
