/** Percent-encoding and decoding of query string components. */

/** Text that cannot be encoded, or a query string that cannot be read. */
export class QueryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "QueryError";
  }
}

/** Characters that encodeURIComponent leaves alone but the catalog API wants encoded. */
const EXTRA = /[!'()*]/g;

/**
 * Percent-encode text for a query string or a path segment: every UTF-8 byte as %XX
 * with upper-case hex digits, except letters, digits, and - . _ ~. Throws a QueryError
 * for text with a lone surrogate, which has no UTF-8 form.
 */
export function encodeComponent(text: string): string {
  let encoded: string;
  try {
    encoded = encodeURIComponent(text);
  } catch {
    throw new QueryError(`cannot encode ${JSON.stringify(text)}: it is not valid Unicode text`);
  }
  return encoded.replace(EXTRA, (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);
}

/**
 * Decode one component of a query string: %XX escapes, and + as a space (HTML forms
 * write a space as +). Throws a QueryError for a malformed escape.
 */
export function decodeComponent(text: string): string {
  try {
    return decodeURIComponent(text.replace(/\+/g, " "));
  } catch {
    throw new QueryError(`malformed percent escape in ${JSON.stringify(text)}`);
  }
}
