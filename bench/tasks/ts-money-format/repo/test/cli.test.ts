import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { run } from "../src/cli.ts";

function cli(...argv: string[]) {
  let out = "";
  let err = "";
  const status = run(argv, {
    out: (text) => {
      out += text;
    },
    err: (text) => {
      err += text;
    },
  });
  return { status, out, err };
}

function withFile(name: string, text: string, fn: (path: string) => void) {
  const dir = mkdtempSync(join(tmpdir(), "moneyfmt-test-"));
  try {
    const path = join(dir, name);
    writeFileSync(path, text);
    fn(path);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("format prints the amount", () => {
  assert.deepEqual(cli("format", "1234.5", "USD"), { status: 0, out: "$1,234.50\n", err: "" });
});

test("format --code prints the code style", () => {
  assert.equal(cli("format", "--code", "1234.5", "USD").out, "1,234.50 USD\n");
});

test("parse prints minor units as JSON", () => {
  assert.equal(cli("parse", "$3.40", "USD").out, '{"minor":340,"currency":"USD"}\n');
});

test("a bad amount exits with status 2", () => {
  const result = cli("format", "abc", "USD");
  assert.equal(result.status, 2);
  assert.equal(result.err, 'moneyfmt: cannot read amount "abc"\n');
});

test("an unknown command prints the usage and exits with status 2", () => {
  const result = cli("frobnicate");
  assert.equal(result.status, 2);
  assert.match(result.err, /^usage: moneyfmt/);
});

test("order prints the statement", () => {
  withFile(
    "o.csv",
    "order,SO-1,USD,10\nsku,description,unit_price,quantity\nA,Thing,5.00,2\n",
    (path) => {
      const result = cli("order", path);
      assert.equal(result.status, 0);
      assert.match(result.out, /^Order SO-1 \(USD\)\n/);
      assert.match(result.out, /Total\s+\$11\.00\n$/);
    },
  );
});

test("export prints the accounting rows", () => {
  withFile(
    "l.csv",
    "date,account,memo,amount,currency\n2027-03-02,4000,Sale,12.5,USD\n",
    (path) => {
      assert.equal(
        cli("export", path).out,
        "date,account,currency,amount,memo\n2027-03-02,4000,USD,12.50,Sale\n",
      );
    },
  );
});

test("a missing file exits with status 2", () => {
  const result = cli("export", "/nonexistent/ledger.csv");
  assert.equal(result.status, 2);
  assert.match(result.err, /^moneyfmt: cannot read \/nonexistent\/ledger\.csv/);
});
