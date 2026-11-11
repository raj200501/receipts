/** Shared types of the gradebook. */

export type Category = "homework" | "quizzes" | "project" | "exams";

/** Points on one assignment: a number, null for missing work, or "EX" when excused. */
export type Points = number | null | "EX";

/** One row of a scores export: a student's result on one assignment. */
export interface ScoreRow {
  student: string;
  name: string;
  assignment: string;
  category: Category;
  points: Points;
  maxPoints: number;
  line: number;
}

/** A student's category percentages (null when the category does not count). */
export type CategoryPercents = Record<Category, number | null>;

/** The final result of one student. */
export interface StudentResult {
  student: string;
  name: string;
  categories: CategoryPercents;
  percent: number;
  letter: string;
}
