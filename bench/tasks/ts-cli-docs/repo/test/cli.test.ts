import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { main, VERSION } from "../src/cli.ts";

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

const LEDGER = `date,category,description,amount
2026-04-01,rent,Rent,1000.00
2026-04-02,groceries,Shop,40.00
2026-05-03,groceries,Shop,60.00
2026-05-04,leisure,Film,15.50
`;

function files(): { ledger: string; rates: string } {
  const dir = mkdtempSync(join(tmpdir(), "ledgerline-cli-"));
  const ledger = join(dir, "ledger.csv");
  const rates = join(dir, "rates.json");
  writeFileSync(ledger, LEDGER);
  writeFileSync(rates, JSON.stringify({ base: "USD", date: "2026-02-02", rates: { USD: 1, EUR: 0.5 } }));
  return { ledger, rates };
}

test("--help and no arguments print the help", () => {
  assert.match(run(["--help"]).out, /Usage: ledgerline <command>/);
  assert.equal(run([]).out, run(["--help"]).out);
});

test("--version prints the version", () => {
  assert.equal(run(["--version"]).out, `${VERSION}\n`);
});

test("summary groups by category by default", () => {
  const { ledger } = files();
  const result = run(["summary", ledger]);
  assert.equal(result.status, 0);
  assert.match(result.out, /^Category/);
  assert.match(result.out, /groceries\s+2\s+100\.00/);
});

test("summary --by month groups by month", () => {
  const { ledger } = files();
  const result = run(["summary", ledger, "--by", "month"]);
  assert.match(result.out, /2026-04\s+2\s+1040\.00/);
  assert.match(result.out, /2026-05\s+2\s+75\.50/);
});

test("summary --min leaves out small expenses", () => {
  const { ledger } = files();
  const result = run(["summary", ledger, "--min", "50"]);
  assert.match(result.out, /Total\s+2\s+1060\.00/);
});

test("summary rejects a bad --by value", () => {
  const { ledger } = files();
  const result = run(["summary", ledger, "--by", "year"]);
  assert.equal(result.status, 2);
  assert.match(result.err, /^ledgerline: --by must be category or month/);
});

test("top shows five expenses by default and -n changes it", () => {
  const { ledger } = files();
  assert.equal(run(["top", ledger]).out.trim().split("\n").length, 4);
  assert.equal(run(["top", ledger, "-n", "2"]).out.trim().split("\n").length, 2);
  assert.equal(run(["top", ledger, "--count", "1"]).out.trim().split("\n").length, 1);
});

test("top rejects a bad count", () => {
  const { ledger } = files();
  assert.equal(run(["top", ledger, "-n", "0"]).status, 2);
});

test("categories lists each category once", () => {
  const { ledger } = files();
  assert.equal(run(["categories", ledger]).out, "groceries (2)\nleisure (1)\nrent (1)\n");
});

test("convert prints the converted amount, the rate, and the date", () => {
  const { rates } = files();
  const result = run(["convert", "10", "usd", "eur", "--rates", rates]);
  assert.equal(result.out, "10.00 USD = 5.00 EUR (rate 0.5000, rates of 2026-02-02)\n");
});

test("convert with an unknown currency exits with status 2", () => {
  const { rates } = files();
  const result = run(["convert", "10", "USD", "ZZZ", "--rates", rates]);
  assert.equal(result.status, 2);
  assert.match(result.err, /no rate for ZZZ/);
});

test("a missing ledger file exits with status 2", () => {
  const result = run(["summary", "/nonexistent/ledger.csv"]);
  assert.equal(result.status, 2);
  assert.match(result.err, /cannot be read/);
});

test("usage errors exit with status 2", () => {
  assert.equal(run(["frobnicate"]).status, 2);
  assert.equal(run(["summary"]).status, 2);
  assert.equal(run(["summary", "x.csv", "--bogus", "1"]).status, 2);
  assert.equal(run(["convert", "10", "USD"]).status, 2);
});
