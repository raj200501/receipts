/** Read assignment scores from CSV text. */

import { CATEGORIES, EXCUSED } from "./policy.ts";
import type { Category, Points, ScoreRow } from "./types.ts";

export const HEADER = "student,name,assignment,category,points,max_points";

/** A row that cannot be read as a score. */
export class ScoreError extends Error {
  line: number;

  constructor(line: number, message: string) {
    super(`line ${line}: ${message}`);
    this.name = "ScoreError";
    this.line = line;
  }
}

function parseNumber(text: string, line: number, field: string): number {
  const value = Number(text);
  if (text === "" || !Number.isFinite(value) || value < 0) {
    throw new ScoreError(line, `${field} must be a number of at least 0, got ${JSON.stringify(text)}`);
  }
  return value;
}

function parsePoints(text: string, line: number): Points {
  if (text === "") {
    return null;
  }
  if (text === EXCUSED) {
    return EXCUSED;
  }
  return parseNumber(text, line, "points");
}

/** Parse one data row; ``line`` is its 1-based line number in the file. */
export function parseRow(text: string, line: number): ScoreRow {
  const fields = text.split(",").map((field) => field.trim());
  if (fields.length !== 6) {
    throw new ScoreError(line, `expected 6 fields, got ${fields.length}`);
  }
  const [student, name, assignment, category, points, maxPoints] = fields;
  if (!student || !name || !assignment) {
    throw new ScoreError(line, "student, name, and assignment must not be empty");
  }
  if (!(CATEGORIES as readonly string[]).includes(category)) {
    throw new ScoreError(line, `unknown category ${JSON.stringify(category)}`);
  }
  const max = parseNumber(maxPoints, line, "max_points");
  if (max === 0) {
    throw new ScoreError(line, "max_points must be greater than 0");
  }
  return {
    student,
    name,
    assignment,
    category: category as Category,
    points: parsePoints(points, line),
    maxPoints: max,
    line,
  };
}

/** Parse a whole export; blank lines are skipped. */
export function parseScores(text: string): ScoreRow[] {
  const lines = text.split(/\r?\n/);
  const rows: ScoreRow[] = [];
  let headerSeen = false;
  lines.forEach((raw, index) => {
    const line = index + 1;
    if (raw.trim() === "") {
      return;
    }
    if (!headerSeen) {
      if (raw.trim() !== HEADER) {
        throw new ScoreError(line, `expected the header ${HEADER}`);
      }
      headerSeen = true;
      return;
    }
    rows.push(parseRow(raw, line));
  });
  return rows;
}
