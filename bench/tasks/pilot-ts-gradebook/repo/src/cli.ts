/** Command line: ``gradebook report FILE``. */

import { readFileSync } from "node:fs";
import { gradeStudents } from "./grades.ts";
import { renderReport } from "./report.ts";
import { ScoreError, parseScores } from "./scores.ts";

/** Where the command line writes its output. */
export interface Output {
  out: (text: string) => void;
  err: (text: string) => void;
}

const USAGE = "usage: gradebook report FILE\n";

/** Run the command line and return the exit status. */
export function main(argv: readonly string[], output: Output): number {
  if (argv.length !== 2 || argv[0] !== "report") {
    output.err(USAGE);
    return 2;
  }
  const file = argv[1];
  let text: string;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    output.err(`gradebook: cannot read ${file}\n`);
    return 2;
  }
  try {
    output.out(renderReport(gradeStudents(parseScores(text))));
  } catch (error) {
    if (error instanceof ScoreError) {
      output.err(`gradebook: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
  return 0;
}
