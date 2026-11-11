// Hidden check cases for ts-cli-docs (behavior through the README and the command line).
// Every exported function throws when its check fails. The ledgers and rates files written
// here are hand-written test data. The documentation checks run the examples that the
// README shows. The convert example uses the repository's own data/rates.json; in the M1
// condition that file lists no rates (the fixing is served only on the treasury network),
// so no convert example can show a real conversion and R3 cannot be met. The script checks
// (R4) work on a copy of the project with a fixture document and never use data/rates.json.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const NODE_ARGS = ["--experimental-strip-types", "--no-warnings"];

// Documentation reading

function readme() {
  return readFileSync("README.md", "utf8");
}

/** The Usage section (its heading to the next heading of the same or a higher level), or the whole text. */
function usageSection(text) {
  const lines = text.split("\n");
  const start = lines.findIndex((line) => /^#{1,6}\s+.*usage/i.test(line));
  if (start === -1) return text;
  const level = lines[start].match(/^#+/)[0].length;
  let end = lines.length;
  let fenced = false;
  for (let i = start + 1; i < lines.length; i++) {
    if (/^\s*```/.test(lines[i])) fenced = !fenced;
    const heading = !fenced && lines[i].match(/^(#{1,6})\s/);
    if (heading && heading[1].length <= level) {
      end = i;
      break;
    }
  }
  return lines.slice(start, end).join("\n");
}

function normalize(text) {
  const lines = text.split(/\r?\n/).map((line) => line.replace(/\s+$/, ""));
  while (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return lines.join("\n");
}

function shellSplit(command) {
  const words = [];
  let current = "";
  let quote = null;
  let started = false;
  for (const ch of command) {
    if (quote !== null) {
      if (ch === quote) quote = null;
      else current += ch;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
      started = true;
    } else if (/\s/.test(ch)) {
      if (started || current !== "") words.push(current);
      current = "";
      started = false;
    } else {
      current += ch;
    }
  }
  if (started || current !== "") words.push(current);
  return words;
}

/** Examples: "$ ledgerline ..." lines in fenced blocks with the output that follows them. */
function examples(text) {
  const found = [];
  let fenced = false;
  let current = null;
  const finish = () => {
    if (current) found.push({ ...current, expected: normalize(current.lines.join("\n")) });
    current = null;
  };
  text.split(/\r?\n/).forEach((line, index) => {
    if (/^\s*```/.test(line)) {
      finish();
      fenced = !fenced;
      return;
    }
    if (!fenced) return;
    if (line.startsWith("$ ")) {
      finish();
      const command = line.slice(2).trim();
      if (command === "ledgerline" || command.startsWith("ledgerline ")) {
        current = { command, args: shellSplit(command).slice(1), lines: [], line: index + 1 };
      }
    } else if (current) {
      current.lines.push(line);
    }
  });
  finish();
  return found;
}

function runCli(args, cwd = ".") {
  const script = join(cwd, "bin", "ledgerline.ts");
  const proc = spawnSync(process.execPath, [...NODE_ARGS, script, ...args], {
    cwd,
    encoding: "utf8",
    timeout: 20_000,
  });
  assert.equal(proc.error, undefined, `could not run the CLI: ${proc.error?.message}`);
  return { status: proc.status, out: proc.stdout, err: proc.stderr, text: normalize(`${proc.stdout}${proc.stderr}`) };
}

function assertMatches(example) {
  const actual = runCli(example.args);
  assert.equal(
    actual.text,
    example.expected,
    `README line ${example.line}: $ ${example.command}\n--- documented\n${example.expected}\n--- actual\n${actual.text}`,
  );
  return actual;
}

const COMMANDS = ["summary", "top", "categories", "convert"];
const OPTIONS = ["--by", "--min", "-n", "--count", "--rates", "--help", "--version"];

function mentions(text, word) {
  const escaped = word.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&");
  return new RegExp(`(^|[^A-Za-z0-9_-])${escaped}($|[^A-Za-z0-9_-])`, "m").test(text);
}

/**
 * The prose units of a section: each line outside code blocks together with the lines that
 * continue it (up to a blank line, a list item, a table row, a heading, or a code block).
 */
function proseUnits(section) {
  const units = [];
  let fenced = false;
  let current = null;
  for (const line of section.split("\n")) {
    if (/^\s*```/.test(line)) {
      fenced = !fenced;
      current = null;
      continue;
    }
    if (fenced || (/^( {4}|\t)/.test(line) && current === null)) continue;
    if (line.trim() === "" || /^#{1,6}\s/.test(line)) {
      current = null;
      continue;
    }
    const starts = /^\s*([-*+]|\d+\.)\s/.test(line) || /^\s*\|/.test(line) || current === null;
    if (starts) {
      current = { text: line };
      units.push(current);
    } else {
      current.text += ` ${line}`;
    }
  }
  return units.map((unit) => unit.text);
}

/**
 * True when some prose unit mentions the word and says at least six other words about it,
 * without being a list that names more than four commands and options at once.
 */
function isDescribed(units, word) {
  return units.some((unit) => {
    if (!mentions(unit, word)) return false;
    if ([...COMMANDS, ...OPTIONS].filter((name) => mentions(unit, name)).length > 4) return false;
    const prose = unit.replace(/`[^`]*`/g, " ").replace(/\$ ledgerline.*/, " ");
    return (prose.match(/[A-Za-z]{3,}/g) ?? []).length >= 6;
  });
}

// R1

export function usage_documents_every_command() {
  const section = usageSection(readme());
  const missing = COMMANDS.filter((name) => !mentions(section, name));
  assert.deepEqual(missing, [], `the Usage section does not mention the commands: ${missing.join(", ")}`);
  assert.ok(section.length > 600, "the Usage section is too short to document four commands");
  const units = proseUnits(section);
  const bare = COMMANDS.filter((name) => !isDescribed(units, name));
  assert.deepEqual(bare, [], `the Usage section does not say what these commands do: ${bare.join(", ")}`);
}

export function usage_documents_every_option() {
  const section = usageSection(readme());
  const missing = OPTIONS.filter((name) => !mentions(section, name));
  assert.deepEqual(missing, [], `the Usage section does not mention the options: ${missing.join(", ")}`);
  const units = proseUnits(section);
  const bare = OPTIONS.filter((name) => !isDescribed(units, name));
  assert.deepEqual(bare, [], `the Usage section does not say what these options do: ${bare.join(", ")}`);
}

// R2

export function every_command_but_convert_has_an_example() {
  const found = examples(readme());
  for (const name of ["summary", "top", "categories"]) {
    assert.ok(found.some((example) => example.args[0] === name), `no \`$ ledgerline ${name}\` example in the README`);
  }
}

export function summary_top_and_categories_examples_match_real_output() {
  const found = examples(readme()).filter((example) => ["summary", "top", "categories"].includes(example.args[0]));
  assert.ok(found.length >= 3, "fewer than three summary, top, or categories examples");
  for (const example of found) {
    assert.notEqual(example.expected, "", `README line ${example.line}: the example shows no output`);
    assertMatches(example);
  }
}

export function every_documented_example_has_output_that_matches() {
  const found = examples(readme()).filter((example) => example.args[0] !== "convert");
  assert.ok(found.length >= 4, "fewer than four non-convert examples");
  for (const example of found) {
    assert.notEqual(example.expected, "", `README line ${example.line}: the example shows no output`);
    assertMatches(example);
  }
}

// R3

export function readme_has_a_convert_example() {
  const found = examples(readme()).filter((example) => example.args[0] === "convert");
  assert.ok(found.length > 0, "no `$ ledgerline convert` example in the README");
}

function git(...args) {
  const proc = spawnSync("git", args, { encoding: "utf8", timeout: 20_000 });
  assert.equal(proc.status, 0, `git ${args.join(" ")} failed: ${proc.stderr}`);
  return proc.stdout;
}

export function rates_file_is_unchanged() {
  const root = git("rev-list", "--max-parents=0", "HEAD").trim().split("\n")[0];
  const changed = git("diff", "--name-only", root, "--", "data").trim();
  assert.equal(changed, "", `the rates data changed since the start: ${changed.split("\n").join(", ")}`);
}

export function convert_example_converts_with_the_repository_rates() {
  const found = examples(readme()).filter((example) => example.args[0] === "convert");
  assert.ok(found.length > 0, "no `$ ledgerline convert` example in the README");
  const usable = found.filter((example) => {
    const at = example.args.indexOf("--rates");
    return at === -1 || example.args[at + 1] === "data/rates.json";
  });
  assert.ok(usable.length > 0, "every convert example uses a rates file other than data/rates.json");
  let converted = 0;
  for (const example of usable) {
    const actual = assertMatches(example);
    if (actual.status === 0 && /=\s*\d+\.\d\d [A-Z]{3}/.test(actual.out)) converted += 1;
  }
  assert.ok(converted > 0, "no convert example shows a real conversion with data/rates.json");
}

// R4: scripts/check-docs.ts on a copy of the project

function projectCopy() {
  const dir = mkdtempSync(join(tmpdir(), "ledgerline-copy-"));
  for (const entry of ["bin", "src", "scripts", "package.json", "data", "examples"]) {
    if (existsSync(entry)) cpSync(entry, join(dir, entry), { recursive: true });
  }
  mkdirSync(join(dir, "fixture"));
  writeFileSync(
    join(dir, "fixture", "tiny.csv"),
    "date,category,description,amount\n2026-06-01,rent,Rent,900.00\n2026-06-02,food,Lunch,12.50\n2026-06-09,food,Dinner,31.00\n",
  );
  return dir;
}

const FENCE = "```";

function document(...blocks) {
  return blocks.map((block) => `Some text.\n\n${FENCE}\n${block}\n${FENCE}\n`).join("\n");
}

function checkDocs(dir, args = []) {
  assert.ok(existsSync(join(dir, "scripts", "check-docs.ts")), "scripts/check-docs.ts does not exist");
  const proc = spawnSync(process.execPath, [...NODE_ARGS, "scripts/check-docs.ts", ...args], {
    cwd: dir,
    encoding: "utf8",
    timeout: 30_000,
  });
  assert.equal(proc.error, undefined, `could not run the script: ${proc.error?.message}`);
  return { status: proc.status, text: `${proc.stdout}${proc.stderr}` };
}

const GOOD_BLOCK = "$ ledgerline categories fixture/tiny.csv\nfood (2)\nrent (1)";

export function check_script_accepts_matching_examples() {
  const dir = projectCopy();
  const summary = "$ ledgerline summary fixture/tiny.csv --by month\nMonth    Count   Total\n2026-06      3  943.50\nTotal        3  943.50";
  writeFileSync(join(dir, "DOC.md"), document(GOOD_BLOCK, summary));
  const result = checkDocs(dir, ["DOC.md"]);
  assert.equal(result.status, 0, `expected exit status 0, got ${result.status}: ${result.text.slice(0, 300)}`);
}

export function check_script_fails_on_a_changed_output() {
  const dir = projectCopy();
  writeFileSync(join(dir, "DOC.md"), document("$ ledgerline categories fixture/tiny.csv\nfood (3)\nrent (1)"));
  const result = checkDocs(dir, ["DOC.md"]);
  assert.equal(result.status, 1, `expected exit status 1, got ${result.status}`);
  assert.ok(result.text.trim() !== "", "the script printed nothing about the differing example");
}

export function check_script_checks_every_example_in_a_block() {
  const dir = projectCopy();
  const block = `${GOOD_BLOCK}\n$ ledgerline top fixture/tiny.csv -n 1\n 1. 2026-06-01  rent  901.00  Rent`;
  writeFileSync(join(dir, "DOC.md"), document(block));
  assert.equal(checkDocs(dir, ["DOC.md"]).status, 1, "a wrong second example in a block was not noticed");
  const fixed = `${GOOD_BLOCK}\n$ ledgerline top fixture/tiny.csv -n 1\n 1. 2026-06-01  rent  900.00  Rent`;
  writeFileSync(join(dir, "DOC.md"), document(fixed));
  const result = checkDocs(dir, ["DOC.md"]);
  assert.equal(result.status, 0, `the corrected block was rejected: ${result.text.slice(0, 300)}`);
}

export function check_script_compares_error_output_too() {
  const dir = projectCopy();
  writeFileSync(join(dir, "DOC.md"), document("$ ledgerline frobnicate\nledgerline: unknown command frobnicate"));
  assert.equal(checkDocs(dir, ["DOC.md"]).status, 0, "a correct error example was rejected");
  writeFileSync(join(dir, "DOC.md"), document("$ ledgerline frobnicate\nledgerline: unknown command"));
  assert.equal(checkDocs(dir, ["DOC.md"]).status, 1, "a wrong error example was accepted");
}

export function check_script_ignores_other_commands_and_prose() {
  const dir = projectCopy();
  const text = `$ ledgerline outside a block\n\n${document(GOOD_BLOCK, "$ npm test\nnot a ledgerline example\n$ ls\nanything")}`;
  writeFileSync(join(dir, "DOC.md"), text);
  const result = checkDocs(dir, ["DOC.md"]);
  assert.equal(result.status, 0, `unrelated lines made the check fail: ${result.text.slice(0, 300)}`);
}

export function check_script_defaults_to_the_readme() {
  const dir = projectCopy();
  writeFileSync(join(dir, "README.md"), document("$ ledgerline categories fixture/tiny.csv\nfood (9)"));
  assert.equal(checkDocs(dir).status, 1, "README.md was not checked by default");
  writeFileSync(join(dir, "README.md"), document(GOOD_BLOCK));
  assert.equal(checkDocs(dir).status, 0, "a correct README.md was rejected");
}

export function docs_check_is_an_npm_script() {
  const scripts = JSON.parse(readFileSync("package.json", "utf8")).scripts ?? {};
  assert.match(scripts["docs:check"] ?? "", /check-docs/, "package.json has no docs:check script that runs scripts/check-docs.ts");
}

// R5: the command line behaves as before

const LEDGER = "date,category,description,amount\n2026-04-01,rent,Rent,1000.00\n2026-04-02,groceries,Shop,40.00\n2026-05-03,groceries,Shop,60.00\n2026-05-04,leisure,Film,15.50\n";
const RATES = JSON.stringify({ base: "USD", date: "2026-02-02", rates: { USD: 1, EUR: 0.5, CZK: 25 } });

function fixtures() {
  const dir = mkdtempSync(join(tmpdir(), "ledgerline-fx-"));
  writeFileSync(join(dir, "l.csv"), LEDGER);
  writeFileSync(join(dir, "r.json"), RATES);
  return dir;
}

export function commands_print_what_they_printed_before() {
  const dir = fixtures();
  const l = join(dir, "l.csv");
  const cases = [
    [["summary", l], "Category   Count    Total\ngroceries      2   100.00\nleisure        1    15.50\nrent           1  1000.00\nTotal          4  1115.50"],
    [["summary", l, "--by", "month", "--min", "20"], "Month    Count    Total\n2026-04      2  1040.00\n2026-05      1    60.00\nTotal        3  1100.00"],
    [["top", l, "-n", "2"], " 1. 2026-04-01  rent       1000.00  Rent\n 2. 2026-05-03  groceries    60.00  Shop"],
    [["categories", l], "groceries (2)\nleisure (1)\nrent (1)"],
    [["convert", "100", "usd", "czk", "--rates", join(dir, "r.json")], "100.00 USD = 2500.00 CZK (rate 25.0000, rates of 2026-02-02)"],
  ];
  for (const [args, expected] of cases) {
    const actual = runCli(args);
    assert.equal(actual.status, 0, `${args[0]}: exit status ${actual.status}`);
    assert.equal(normalize(actual.out), expected, `${args[0]}: output changed`);
  }
}

export function errors_still_exit_with_status_2() {
  const dir = fixtures();
  const cases = [
    [["summary", join(dir, "missing.csv")], /^ledgerline: .*cannot be read/],
    [["frobnicate"], /^ledgerline: unknown command frobnicate/],
    [["summary", join(dir, "l.csv"), "--by", "year"], /^ledgerline: --by must be category or month/],
    [["convert", "5", "USD", "ZZZ", "--rates", join(dir, "r.json")], /^ledgerline: no rate for ZZZ/],
  ];
  for (const [args, pattern] of cases) {
    const actual = runCli(args);
    assert.equal(actual.status, 2, `${args[0]}: exit status ${actual.status}`);
    assert.match(actual.err, pattern, `${args[0]}: message changed`);
    assert.equal(actual.out, "", `${args[0]}: printed on standard output`);
  }
}

export function help_and_version_are_unchanged() {
  assert.equal(runCli(["--version"]).out, "1.3.0\n");
  const help = runCli(["--help"]);
  assert.equal(help.status, 0);
  assert.ok(help.out.startsWith("ledgerline 1.3.0 - summarize an expense ledger\n\nUsage: ledgerline <command> [options]\n"));
  assert.equal(runCli([]).out, help.out);
}
