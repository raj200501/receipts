/** The command line: convert, mix, and contrast. */

import { ArgError, lastValue, parseArgs } from "./args.ts";
import type { ArgSpec } from "./args.ts";
import { contrastRatio, meetsContrast } from "./contrast.ts";
import { ColorError } from "./errors.ts";
import { toHex, toRgbString } from "./format.ts";
import { formatHsl } from "./hsl.ts";
import { mix } from "./mix.ts";
import { parseColor } from "./parse.ts";
import type { Io } from "./types.ts";

const SPEC: ArgSpec = { values: ["to", "amount"], flags: [] };

const USAGE = `usage: color COMMAND

commands:
  convert COLOR [--to hex|rgb|hsl]   print a color in another notation (hex by default)
  mix A B [--amount N]               blend two colors (N from 0 to 1, default 0.5), as hex
  contrast FOREGROUND BACKGROUND     print the contrast ratio and the AA and AAA results
  help                               show this text
`;

function run(argv: readonly string[], io: Io): number {
  const parsed = parseArgs(argv, SPEC);
  const [command, ...rest] = parsed.positional;
  if (command === undefined || command === "help") {
    (command === undefined ? io.err : io.out)(USAGE);
    return command === undefined ? 2 : 0;
  }
  if (command === "convert") {
    if (rest.length !== 1) {
      throw new ArgError("convert needs exactly one color");
    }
    const color = parseColor(rest[0]);
    const target = lastValue(parsed, "to") ?? "hex";
    if (target === "hex") {
      io.out(`${toHex(color)}\n`);
    } else if (target === "rgb") {
      io.out(`${toRgbString(color)}\n`);
    } else if (target === "hsl") {
      io.out(`${formatHsl(color)}\n`);
    } else {
      throw new ArgError(`unknown notation "${target}" (use hex, rgb, or hsl)`);
    }
    return 0;
  }
  if (command === "mix") {
    if (rest.length !== 2) {
      throw new ArgError("mix needs two colors");
    }
    const text = lastValue(parsed, "amount") ?? "0.5";
    const amount = Number(text);
    if (text.trim() === "" || Number.isNaN(amount)) {
      throw new ArgError(`"${text}" is not a number`);
    }
    io.out(`${toHex(mix(parseColor(rest[0]), parseColor(rest[1]), amount))}\n`);
    return 0;
  }
  if (command === "contrast") {
    if (rest.length !== 2) {
      throw new ArgError("contrast needs a foreground and a background color");
    }
    const [foreground, background] = [parseColor(rest[0]), parseColor(rest[1])];
    const verdict = (level: "AA" | "AAA", size: "normal" | "large") =>
      `${level} ${size} ${meetsContrast(foreground, background, level, size) ? "pass" : "fail"}\n`;
    io.out(`ratio ${contrastRatio(foreground, background).toFixed(2)}:1\n`);
    io.out(verdict("AA", "normal") + verdict("AA", "large"));
    io.out(verdict("AAA", "normal") + verdict("AAA", "large"));
    return 0;
  }
  throw new ArgError(`unknown command "${command}" (try "color help")`);
}

/** Run the command line and return the exit status: 0 on success, 2 for bad input. */
export function main(argv: readonly string[], io: Io): number {
  try {
    return run(argv, io);
  } catch (error) {
    if (error instanceof ArgError || error instanceof ColorError) {
      io.err(`color: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}
