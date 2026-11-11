/** Errors that the command line reports as "ledgerline: message" with exit status 2. */

/** The command line itself is wrong: unknown command, missing or bad argument. */
export class UsageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UsageError";
  }
}

/** An input file cannot be used: missing, malformed, or without the data needed. */
export class DataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DataError";
  }
}
