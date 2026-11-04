/** The CSV dialect: which character separates the fields of a record. */

/** Options that describe a CSV dialect. */
export interface Dialect {
  /** The field delimiter: one character, a comma unless told otherwise. */
  delimiter: string;
}

export const DEFAULT_DELIMITER = ",";

/** Characters that can never be the delimiter, with the words the error uses for them. */
const RESERVED: ReadonlyMap<string, string> = new Map([
  ['"', "the double quote"],
  ["\n", "a line break"],
  ["\r", "a line break"],
]);

/** A delimiter that cannot be used. */
export class DialectError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DialectError";
  }
}

/** The dialect for ``options``; throws a DialectError when the delimiter cannot be used. */
export function resolveDialect(options: Partial<Dialect> = {}): Dialect {
  const delimiter = options.delimiter ?? DEFAULT_DELIMITER;
  if (delimiter.length !== 1) {
    throw new DialectError(`the delimiter must be one character, got ${JSON.stringify(delimiter)}`);
  }
  const reserved = RESERVED.get(delimiter);
  if (reserved !== undefined) {
    throw new DialectError(`the delimiter cannot be ${reserved}`);
  }
  return { delimiter };
}

/** The delimiter a --delimiter value names: `tab` and `\t` mean a tab, anything else itself. */
export function delimiterOption(value: string): string {
  return value === "tab" || value === "\\t" ? "\t" : value;
}
