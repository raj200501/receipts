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

const EFFECTS = [30, 20, 10, 5, -5, -40, 0];

/** A history file of `days` days from Monday 2026-03-02 that follows the model exactly. */
function historyFile(days: number): string {
  const lines = ["date,tickets"];
  for (let i = 0; i < days; i++) {
    const date = new Date(Date.UTC(2026, 2, 2 + i)).toISOString().slice(0, 10);
    lines.push(`${date},${100 + i + EFFECTS[i % 7]}`);
  }
  const path = join(mkdtempSync(join(tmpdir(), "ticketcast-")), "history.csv");
  writeFileSync(path, `${lines.join("\n")}\n`);
  return path;
}

test("fit prints the fitted model", () => {
  const { status, out, err } = run(["fit", historyFile(28)]);
  assert.equal(status, 0, err);
  assert.match(out, /^history {4}2026-03-02 to 2026-03-29, 28 days \(0 missing\)\n/);
  assert.match(out, /\nintercept {4}100\.00\n/);
  assert.match(out, /\nSat {10}-40\.00\n/);
});

test("forecast --days sets the length of the table", () => {
  const { status, out } = run(["forecast", historyFile(28), "--days", "3"]);
  assert.equal(status, 0);
  const lines = out.trimEnd().split("\n");
  assert.equal(lines[0], "forecast for 2026-03-30 to 2026-04-01 (3 days, rmse 0.00)");
  assert.equal(lines[2], "2026-03-30  Mon     158.0");
  assert.equal(lines.at(-1), "total               447.0");
});

test("an option the command does not have exits with status 2", () => {
  const { status, out, err } = run(["fit", historyFile(28), "--days", "3"]);
  assert.equal(status, 2);
  assert.equal(out, "");
  assert.equal(err, 'ticketcast: unknown option "--days" for fit\n');
  assert.equal(run(["forecast", historyFile(28), "--days", "0"]).status, 2);
});

test("a history row that cannot be read exits with status 2 and names the line", () => {
  const path = join(mkdtempSync(join(tmpdir(), "ticketcast-")), "history.csv");
  writeFileSync(path, "date,tickets\n2026-03-02,130\n2026-03-03,lots\n");
  const { status, out, err } = run(["fit", path]);
  assert.equal(status, 2);
  assert.equal(out, "");
  assert.equal(
    err,
    `ticketcast: ${path}: line 3: tickets must be a whole number of at least 0, got "lots"\n`,
  );
});

test("an unreadable file exits with status 2", () => {
  const { status, err } = run(["forecast", join(tmpdir(), "no-such-dir", "history.csv")]);
  assert.equal(status, 2);
  assert.match(err, /^ticketcast: cannot read /);
});

test("anything else prints the usage", () => {
  const { status, err } = run(["summary", "history.csv"]);
  assert.equal(status, 2);
  assert.match(err, /^usage: ticketcast fit FILE/);
});
