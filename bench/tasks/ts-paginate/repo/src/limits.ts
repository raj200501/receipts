/** The page size rules shared by every kind of list request. */

/** Items per page when the caller does not say. */
export const DEFAULT_PER_PAGE = 20;

/** The most items one page may hold; larger requests are cut down to this. */
export const MAX_PER_PAGE = 100;

/**
 * The page size to use for a requested size.
 *
 * No size means the default. A size that is not a whole number of at least 1 is a
 * programming error and throws a RangeError. A larger size than the limit is not an
 * error: it is cut down to `MAX_PER_PAGE`.
 */
export function resolveSize(value: number | undefined): number {
  if (value === undefined) {
    return DEFAULT_PER_PAGE;
  }
  if (!Number.isInteger(value) || value < 1) {
    throw new RangeError(`page size must be a whole number of at least 1, got ${value}`);
  }
  return Math.min(value, MAX_PER_PAGE);
}
