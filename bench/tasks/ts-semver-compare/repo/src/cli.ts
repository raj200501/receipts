/** Command line: ``vercmp compare|sort|latest|bump``. */

import { readFileSync } from "node:fs";
import type { BumpLevel } from "./bump.ts";
import { BUMP_LEVELS, DEFAULT_PREID, bumpVersion } from "./bump.ts";
import { compareVersions, latestVersion, sortVersions } from "./compare.ts";
import { readVersionList } from "./list.ts";
import { VersionError } from "./version.ts";

/** Where the command line writes its output. */
export interface Output {
  out: (text: string) => void;
  err: (text: string) => void;
}

export const USAGE = [
  "usage: vercmp compare A B",
  "       vercmp sort [--reverse] FILE",
  "       vercmp latest [--pre] FILE",
  "       vercmp bump major|minor|patch|pre|release VERSION [--preid NAME]",
  "",
].join("\n");

/** The command line is not one vercmp understands; the usage is printed. */
class UsageError extends Error {}

/** A problem that stops a command with exit status 2. */
class CommandError extends Error {}

interface Arguments {
  flags: Set<string>;
  values: Map<string, string>;
  words: string[];
}

/** Split the words after the command into known flags, flag values, and the rest. */
function parseArguments(
  argv: readonly string[],
  flags: readonly string[],
  valued: readonly string[] = [],
): Arguments {
  const parsed: Arguments = { flags: new Set(), values: new Map(), words: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const word = argv[index];
    if (flags.includes(word)) {
      parsed.flags.add(word);
    } else if (valued.includes(word)) {
      const value = argv[index + 1];
      if (value === undefined) {
        throw new UsageError(`${word} needs a value`);
      }
      parsed.values.set(word, value);
      index += 1;
    } else if (word.startsWith("--")) {
      throw new UsageError(`unknown option ${word}`);
    } else {
      parsed.words.push(word);
    }
  }
  return parsed;
}

function readList(file: string): string[] {
  let text: string;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    throw new CommandError(`cannot read ${file}`);
  }
  return readVersionList(text);
}

function lines(versions: readonly string[]): string {
  return versions.map((version) => `${version}\n`).join("");
}

function run(argv: readonly string[], output: Output): number {
  const [command, ...rest] = argv;
  if (command === "compare") {
    const { words } = parseArguments(rest, []);
    if (words.length !== 2) {
      throw new UsageError("compare needs two versions");
    }
    output.out(`${compareVersions(words[0], words[1])}\n`);
    return 0;
  }
  if (command === "sort") {
    const { flags, words } = parseArguments(rest, ["--reverse"]);
    if (words.length !== 1) {
      throw new UsageError("sort needs one file");
    }
    output.out(lines(sortVersions(readList(words[0]), { reverse: flags.has("--reverse") })));
    return 0;
  }
  if (command === "latest") {
    const { flags, words } = parseArguments(rest, ["--pre"]);
    if (words.length !== 1) {
      throw new UsageError("latest needs one file");
    }
    const includePrerelease = flags.has("--pre");
    const latest = latestVersion(readList(words[0]), { includePrerelease });
    if (latest === null) {
      output.err(`vercmp: no ${includePrerelease ? "version" : "release"} in ${words[0]}\n`);
      return 1;
    }
    output.out(`${latest}\n`);
    return 0;
  }
  if (command === "bump") {
    const { values, words } = parseArguments(rest, [], ["--preid"]);
    const [level, version] = words;
    if (words.length !== 2 || !(BUMP_LEVELS as readonly string[]).includes(level)) {
      throw new UsageError("bump needs a level and a version");
    }
    const preid = values.get("--preid") ?? DEFAULT_PREID;
    output.out(`${bumpVersion(version, level as BumpLevel, preid)}\n`);
    return 0;
  }
  throw new UsageError(command === undefined ? "no command" : `unknown command ${command}`);
}

/** Run the command line and return the exit status. */
export function main(argv: readonly string[], output: Output): number {
  try {
    return run(argv, output);
  } catch (error) {
    if (error instanceof UsageError) {
      output.err(USAGE);
      return 2;
    }
    if (error instanceof VersionError || error instanceof CommandError) {
      output.err(`vercmp: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}
