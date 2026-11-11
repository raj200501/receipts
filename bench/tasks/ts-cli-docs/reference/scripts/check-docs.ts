/**
 * Check the examples in a Markdown file against the real command line.
 *
 *     node --experimental-strip-types scripts/check-docs.ts [FILE]
 *
 * FILE defaults to README.md. An example is a line that starts with "$ ledgerline" inside a
 * fenced code block; the lines after it, up to the next "$ " line or the end of the block,
 * are the output the documentation promises. Every example is run from the project root
 * and its standard output (followed by its standard error) is compared with that text,
 * ignoring trailing spaces and trailing blank lines. Exit status: 0 when every example
 * matches, 1 when one differs, 2 when the file cannot be read.
 */
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PROGRAM = "ledgerline";

export interface Example {
  /** The command as written, without the "$ ". */
  command: string;
  /** The output the documentation shows. */
  expected: string;
  /** 1-based line of the command in the Markdown file. */
  line: number;
}

/** Split a command line into words; single and double quotes group words. */
export function shellSplit(command: string): string[] {
  const words: string[] = [];
  let current = "";
  let quote: string | null = null;
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

function normalize(text: string): string {
  const lines = text.split(/\r?\n/).map((line) => line.replace(/\s+$/, ""));
  while (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return lines.join("\n");
}

/** Find the "$ ledgerline ..." examples in the fenced code blocks of a Markdown text. */
export function extractExamples(markdown: string): Example[] {
  const examples: Example[] = [];
  let inFence = false;
  let current: { command: string; lines: string[]; line: number } | null = null;
  const finish = () => {
    if (current !== null) {
      examples.push({
        command: current.command,
        expected: normalize(current.lines.join("\n")),
        line: current.line,
      });
      current = null;
    }
  };
  markdown.split(/\r?\n/).forEach((text, index) => {
    if (/^\s*```/.test(text)) {
      finish();
      inFence = !inFence;
      return;
    }
    if (!inFence) return;
    if (text.startsWith("$ ")) {
      finish();
      const command = text.slice(2).trim();
      if (command === PROGRAM || command.startsWith(`${PROGRAM} `)) {
        current = { command, lines: [], line: index + 1 };
      }
    } else if (current !== null) {
      current.lines.push(text);
    }
  });
  finish();
  return examples;
}

/** Run one example from the project root and return what it printed. */
export function runExample(example: Example, root: string = PROJECT_ROOT): string {
  const args = shellSplit(example.command).slice(1);
  const proc = spawnSync(
    process.execPath,
    ["--experimental-strip-types", "--no-warnings", join(root, "bin", "ledgerline.ts"), ...args],
    { cwd: root, encoding: "utf8", timeout: 20_000 },
  );
  return normalize(`${proc.stdout ?? ""}${proc.stderr ?? ""}`);
}

/** Compare every example in a Markdown text with the real output; returns the problems. */
export function checkMarkdown(markdown: string, root: string = PROJECT_ROOT): string[] {
  const problems: string[] = [];
  for (const example of extractExamples(markdown)) {
    const actual = runExample(example, root);
    if (actual !== example.expected) {
      problems.push(
        `line ${example.line}: $ ${example.command}\n--- documented\n${example.expected}\n--- actual\n${actual}`,
      );
    }
  }
  return problems;
}

function main(argv: string[]): number {
  const file = argv[0] ?? join(PROJECT_ROOT, "README.md");
  let markdown: string;
  try {
    markdown = readFileSync(file, "utf8");
  } catch {
    console.error(`check-docs: cannot read ${file}`);
    return 2;
  }
  const count = extractExamples(markdown).length;
  const problems = checkMarkdown(markdown);
  for (const problem of problems) console.log(problem);
  if (problems.length > 0) {
    console.log(`check-docs: ${problems.length} of ${count} examples differ from the real output`);
    return 1;
  }
  console.log(`check-docs: ${count} examples match`);
  return 0;
}

if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = main(process.argv.slice(2));
}
