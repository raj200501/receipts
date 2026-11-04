import type { Problem } from "./rules.ts";

/** One line per problem: "CHANGELOG.md:12: date-format: message". */
export function formatProblems(file: string, problems: Problem[]): string {
  return problems.map((p) => `${file}:${p.line}: ${p.rule}: ${p.message}`).join("\n");
}

/** The closing line of a run, with the right plural. */
export function summaryLine(count: number): string {
  return count === 0 ? "no problems found" : `${count} ${count === 1 ? "problem" : "problems"} found`;
}
