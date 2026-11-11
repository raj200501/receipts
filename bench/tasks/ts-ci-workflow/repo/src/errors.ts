/** Raised for a command line that cannot be run; the CLI exits with status 2. */
export class UsageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UsageError";
  }
}
