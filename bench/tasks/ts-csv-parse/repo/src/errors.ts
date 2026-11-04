/** The error for input that does not follow the CSV format (or the JSON lines format). */

/** A problem in the input; ``line`` is the 1-based line it was found on. */
export class CsvError extends Error {
  readonly line: number;

  constructor(line: number, message: string) {
    super(`line ${line}: ${message}`);
    this.name = "CsvError";
    this.line = line;
  }
}
