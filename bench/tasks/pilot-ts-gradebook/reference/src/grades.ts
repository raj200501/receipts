/** Category percentages, final percentages, and letter grades. */

import { CATEGORIES, EXCUSED, LETTER_BANDS, WEIGHTS } from "./policy.ts";
import type { CategoryPercents, ScoreRow, StudentResult } from "./types.ts";

/**
 * A student's percentage over the rows of one category, or null when none of them
 * counts. Excused rows are left out entirely; missing work counts as zero points.
 */
export function categoryPercent(rows: readonly ScoreRow[]): number | null {
  let earned = 0;
  let possible = 0;
  for (const row of rows) {
    if (row.points === EXCUSED) {
      continue;
    }
    earned += row.points ?? 0;
    possible += row.maxPoints;
  }
  return possible === 0 ? null : (100 * earned) / possible;
}

/**
 * The weighted final percentage from a student's category percentages. A category
 * that does not count (null) is left out, and its weight is shared among the other
 * categories in proportion to their weights (docs/GRADING.md).
 */
export function finalPercent(categories: CategoryPercents): number {
  let total = 0;
  let weight = 0;
  for (const category of CATEGORIES) {
    const percent = categories[category];
    if (percent === null) {
      continue;
    }
    total += WEIGHTS[category] * percent;
    weight += WEIGHTS[category];
  }
  return weight === 0 ? 0 : total / weight;
}

/** The letter grade for a final percentage, taken as it is (89.99 is a B+). */
export function letterGrade(percent: number): string {
  for (const [lowest, letter] of LETTER_BANDS) {
    if (percent >= lowest) {
      return letter;
    }
  }
  return "F";
}

/** Every student's result, in student id order. */
export function gradeStudents(rows: readonly ScoreRow[]): StudentResult[] {
  const byStudent = new Map<string, ScoreRow[]>();
  for (const row of rows) {
    const list = byStudent.get(row.student) ?? [];
    list.push(row);
    byStudent.set(row.student, list);
  }
  const results: StudentResult[] = [];
  for (const student of [...byStudent.keys()].sort()) {
    const own = byStudent.get(student) ?? [];
    const categories = {} as CategoryPercents;
    for (const category of CATEGORIES) {
      categories[category] = categoryPercent(own.filter((row) => row.category === category));
    }
    const percent = finalPercent(categories);
    results.push({ student, name: own[0].name, categories, percent, letter: letterGrade(percent) });
  }
  return results;
}
