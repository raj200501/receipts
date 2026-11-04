/** Class statistics over final percentages. */

import { LETTER_BANDS } from "./policy.ts";
import type { StudentResult } from "./types.ts";

/** The arithmetic mean (0 for no values). */
export function mean(values: readonly number[]): number {
  if (values.length === 0) {
    return 0;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

/** The median (0 for no values). */
export function median(values: readonly number[]): number {
  if (values.length === 0) {
    return 0;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/** How many students got each letter, best letter first; letters nobody got are left out. */
export function letterCounts(results: readonly StudentResult[]): Array<[string, number]> {
  const counts: Array<[string, number]> = [];
  for (const [, letter] of LETTER_BANDS) {
    const count = results.filter((result) => result.letter === letter).length;
    if (count > 0) {
      counts.push([letter, count]);
    }
  }
  return counts;
}
