/** Read raw environment strings as typed values. */

/** A raw value that cannot be read as the expected kind of value. */
export class CoercionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CoercionError";
  }
}

function quoted(raw: string): string {
  return JSON.stringify(raw);
}

const INTEGER = /^[+-]?\d+$/;

/** A whole decimal number such as 8080 or -3. */
export function parseInteger(raw: string): number {
  if (!INTEGER.test(raw)) {
    throw new CoercionError(`expected an integer, got ${quoted(raw)}`);
  }
  const value = Number(raw);
  if (!Number.isSafeInteger(value)) {
    throw new CoercionError(`expected an integer, got ${quoted(raw)} (too large)`);
  }
  return value;
}

const TRUE_WORDS = new Set(["true", "1", "yes", "on"]);
const FALSE_WORDS = new Set(["false", "0", "no", "off"]);

/** true, false, 1, 0, yes, no, on, or off, in any case. */
export function parseBoolean(raw: string): boolean {
  const word = raw.toLowerCase();
  if (TRUE_WORDS.has(word)) {
    return true;
  }
  if (FALSE_WORDS.has(word)) {
    return false;
  }
  throw new CoercionError(`expected true or false, got ${quoted(raw)}`);
}

const DURATION = /^(\d+)(ms|s|m|h)$/;
const UNIT_MS: Readonly<Record<string, number>> = { ms: 1, s: 1_000, m: 60_000, h: 3_600_000 };

/** A whole number and a unit (250ms, 30s, 5m, 1h), read as milliseconds. */
export function parseDuration(raw: string): number {
  const match = DURATION.exec(raw);
  if (match === null) {
    throw new CoercionError(`expected a duration such as 250ms, 30s, or 5m, got ${quoted(raw)}`);
  }
  return Number(match[1]) * UNIT_MS[match[2]];
}

const DISPLAY_UNITS: ReadonlyArray<readonly [string, number]> = [
  ["h", 3_600_000],
  ["m", 60_000],
  ["s", 1_000],
];

/** A duration in milliseconds, in the largest unit that divides it (30000 is 30s). */
export function formatDuration(ms: number): string {
  for (const [unit, size] of DISPLAY_UNITS) {
    if (ms !== 0 && ms % size === 0) {
      return `${ms / size}${unit}`;
    }
  }
  return `${ms}ms`;
}

/** Comma-separated items; spaces around items and empty items are dropped. */
export function parseList(raw: string): string[] {
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "");
}

/**
 * An absolute URL, read in its normalized form. ``protocols`` limits the schemes
 * (written without the colon, for example ["https"]); empty means any scheme.
 */
export function parseUrl(raw: string, protocols: readonly string[] = []): string {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new CoercionError(`expected an absolute URL, got ${quoted(raw)}`);
  }
  const scheme = url.protocol.slice(0, -1);
  if (protocols.length > 0 && !protocols.includes(scheme)) {
    const allowed = protocols.map((name) => `${name}://`).join(" or ");
    throw new CoercionError(`expected a URL starting with ${allowed}, got ${quoted(raw)}`);
  }
  return url.href;
}
