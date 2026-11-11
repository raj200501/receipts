/** The error emit throws when listeners failed. */

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Errors thrown by listeners during one emit; every listener was still called. */
export class EmitError extends Error {
  /** The event whose listeners failed. */
  readonly event: string;
  /** What the failing listeners threw, in the order they were called. */
  readonly errors: readonly unknown[];

  constructor(event: string, errors: readonly unknown[]) {
    const count = errors.length === 1 ? "1 listener" : `${errors.length} listeners`;
    super(`${count} of ${JSON.stringify(event)} failed: ${errors.map(describe).join("; ")}`);
    this.name = "EmitError";
    this.event = event;
    this.errors = errors;
  }
}
