/** Request targets: the path of a target, and percent-decoding of parameter values. */

/** A request target or a parameter value that the router cannot read. */
export class PathError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PathError";
  }
}

/** The path of a request target: everything before its query string or fragment. */
export function requestPath(target: string): string {
  const end = target.search(/[?#]/);
  const path = end === -1 ? target : target.slice(0, end);
  if (!path.startsWith("/")) {
    throw new PathError(`the request target must start with /, got ${JSON.stringify(target)}`);
  }
  return path;
}

/** One percent-encoded value as text (``Ada%20L`` is ``Ada L``). */
export function decodeValue(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    throw new PathError(`invalid percent-encoding in ${JSON.stringify(value)}`);
  }
}
