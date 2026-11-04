/** The grading policy from docs/GRADING.md as data. */

import type { Category } from "./types.ts";

export const CATEGORIES: readonly Category[] = ["homework", "quizzes", "project", "exams"];

/** Category weights; they add up to 1. */
export const WEIGHTS: Readonly<Record<Category, number>> = {
  homework: 0.3,
  quizzes: 0.2,
  project: 0.2,
  exams: 0.3,
};

/** The lowest final percentage of each letter, best letter first. */
export const LETTER_BANDS: ReadonlyArray<readonly [number, string]> = [
  [93, "A"],
  [90, "A-"],
  [87, "B+"],
  [83, "B"],
  [80, "B-"],
  [77, "C+"],
  [73, "C"],
  [70, "C-"],
  [60, "D"],
  [0, "F"],
];

/** The points value of an excused assignment. */
export const EXCUSED = "EX";
