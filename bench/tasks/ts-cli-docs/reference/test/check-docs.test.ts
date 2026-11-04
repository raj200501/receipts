import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { checkMarkdown, extractExamples, shellSplit } from "../scripts/check-docs.ts";

const FENCE = "```";

function ledger(): string {
  const dir = mkdtempSync(join(tmpdir(), "ledgerline-docs-"));
  const path = join(dir, "tiny.csv");
  writeFileSync(path, "date,category,description,amount\n2026-06-01,rent,Rent,900.00\n2026-06-02,food,Lunch,12.50\n");
  return path;
}

function doc(...blocks: string[]): string {
  return blocks.map((block) => `Some text.\n\n${FENCE}\n${block}\n${FENCE}\n`).join("\n");
}

test("shellSplit splits words and honours quotes", () => {
  assert.deepEqual(shellSplit("ledgerline summary 'my file.csv' --by month"), [
    "ledgerline",
    "summary",
    "my file.csv",
    "--by",
    "month",
  ]);
  assert.deepEqual(shellSplit('a "" b'), ["a", "", "b"]);
});

test("extractExamples finds ledgerline commands in fenced blocks only", () => {
  const text = [
    "$ ledgerline outside",
    "",
    FENCE,
    "$ ledgerline categories x.csv",
    "food (1)",
    "$ npm test",
    "ignored",
    "$ ledgerline --version",
    "1.3.0",
    FENCE,
  ].join("\n");
  const found = extractExamples(text);
  assert.deepEqual(
    found.map((example) => [example.command, example.expected]),
    [
      ["ledgerline categories x.csv", "food (1)"],
      ["ledgerline --version", "1.3.0"],
    ],
  );
});

test("checkMarkdown accepts examples that match", () => {
  const path = ledger();
  const text = doc(`$ ledgerline categories ${path}\nfood (1)\nrent (1)`);
  assert.deepEqual(checkMarkdown(text), []);
});

test("checkMarkdown reports an example whose output differs", () => {
  const path = ledger();
  const problems = checkMarkdown(doc(`$ ledgerline categories ${path}\nfood (2)\nrent (1)`));
  assert.equal(problems.length, 1);
  assert.match(problems[0] ?? "", /food \(2\)/);
});

test("checkMarkdown compares error messages too", () => {
  const text = doc("$ ledgerline frobnicate\nledgerline: unknown command frobnicate");
  assert.deepEqual(checkMarkdown(text), []);
});

test("trailing spaces and blank lines do not matter", () => {
  const text = doc("$ ledgerline --version\n1.3.0   \n\n");
  assert.deepEqual(checkMarkdown(text), []);
});
