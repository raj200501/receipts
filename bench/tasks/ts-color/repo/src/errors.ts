/** Errors raised for colors that cannot be read or used. */

/** Thrown for text that is not a color this package understands, or an out-of-range value. */
export class ColorError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ColorError";
  }
}
