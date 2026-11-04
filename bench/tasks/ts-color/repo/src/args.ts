/** A small command-line argument parser: words, flags, and options that take a value. */

/** Thrown for an option that is unknown or that lacks its value. */
export class ArgError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ArgError";
  }
}

/** The options a command line may use, without their leading dashes. */
export interface ArgSpec {
  /** Options that take a value (`--file todos.json` or `--file=todos.json`). */
  values: readonly string[];
  /** Options that stand alone (`--open`). */
  flags: readonly string[];
}

export interface ParsedArgs {
  positional: string[];
  /** Every value given for an option, in order (an option may be repeated). */
  values: Map<string, string[]>;
  flags: Set<string>;
}

/** Split an argument list into words, flags, and option values. */
export function parseArgs(argv: readonly string[], spec: ArgSpec): ParsedArgs {
  const parsed: ParsedArgs = { positional: [], values: new Map(), flags: new Set() };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith("--") || arg === "--") {
      parsed.positional.push(arg);
      continue;
    }
    const equals = arg.indexOf("=");
    const name = equals === -1 ? arg.slice(2) : arg.slice(2, equals);
    if (spec.flags.includes(name) && equals === -1) {
      parsed.flags.add(name);
    } else if (spec.values.includes(name)) {
      let value: string | undefined;
      if (equals === -1) {
        index += 1;
        value = argv[index];
      } else {
        value = arg.slice(equals + 1);
      }
      if (value === undefined) {
        throw new ArgError(`--${name} needs a value`);
      }
      parsed.values.set(name, [...(parsed.values.get(name) ?? []), value]);
    } else {
      throw new ArgError(`unknown option --${name}`);
    }
  }
  return parsed;
}

/** The last value given for an option, or undefined. */
export function lastValue(parsed: ParsedArgs, name: string): string | undefined {
  return parsed.values.get(name)?.at(-1);
}
