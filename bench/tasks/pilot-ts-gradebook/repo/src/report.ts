/** The plain-text class report. */

import { CATEGORIES } from "./policy.ts";
import { letterCounts, mean, median } from "./stats.ts";
import type { StudentResult } from "./types.ts";

/** Format a percentage with one decimal place, or "-" when it does not count. */
export function formatPercent(value: number | null): string {
  return value === null ? "-" : value.toFixed(1);
}

/** The report: a table with one line per student, then the class summary. */
export function renderReport(results: readonly StudentResult[]): string {
  const header = ["student ", "name".padEnd(16), ...CATEGORIES.map((c) => c.padStart(9))];
  const lines = [[...header, "    final", "  letter"].join("")];
  for (const result of results) {
    const cells = CATEGORIES.map((c) => formatPercent(result.categories[c]).padStart(9));
    lines.push(
      [
        result.student.padEnd(8),
        result.name.padEnd(16),
        ...cells,
        formatPercent(result.percent).padStart(9),
        `  ${result.letter}`,
      ].join(""),
    );
  }
  const finals = results.map((result) => result.percent);
  const letters = letterCounts(results).map(([letter, count]) => `${letter} ${count}`);
  lines.push(
    "",
    `students: ${results.length}`,
    `mean: ${formatPercent(mean(finals))}`,
    `median: ${formatPercent(median(finals))}`,
    `letters: ${letters.join(", ") || "-"}`,
  );
  return `${lines.join("\n")}\n`;
}
