/** Errors raised for bad request parameters. */

/** Thrown when the query parameters of a list request cannot be used. The API answers 400. */
export class PageParamsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PageParamsError";
  }
}
