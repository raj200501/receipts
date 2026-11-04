/** Reading and writing single versions: ``MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]``. */

/** A parsed version (docs/VERSIONING.md, "Version format"). */
export interface Version {
  major: number;
  minor: number;
  patch: number;
  /** The prerelease identifiers; empty for a release. */
  prerelease: readonly string[];
  /** The build metadata identifiers; empty when there is none. */
  build: readonly string[];
  /** Whether the text started with "v", as git tags do. */
  tagged: boolean;
}

/** A text that is not a version. */
export class VersionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "VersionError";
  }
}

const PATTERN = /^(v?)(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$/;
const IDENTIFIER = /^[0-9A-Za-z-]+$/;
const NUMERIC = /^\d+$/;

function invalid(text: string, reason?: string): VersionError {
  const suffix = reason === undefined ? "" : ` (${reason})`;
  return new VersionError(`not a version: ${JSON.stringify(text)}${suffix}`);
}

function readNumber(digits: string, text: string): number {
  if (digits.length > 1 && digits.startsWith("0")) {
    throw invalid(text, `leading zero in ${digits}`);
  }
  const value = Number(digits);
  if (!Number.isSafeInteger(value)) {
    throw invalid(text, `${digits} is too large`);
  }
  return value;
}

function readIdentifiers(part: string | undefined, text: string, prerelease: boolean): string[] {
  if (part === undefined) {
    return [];
  }
  const identifiers = part.split(".");
  for (const identifier of identifiers) {
    if (!IDENTIFIER.test(identifier)) {
      throw invalid(text, "empty identifier");
    }
    if (prerelease && NUMERIC.test(identifier) && identifier.length > 1 && identifier.startsWith("0")) {
      throw invalid(text, `leading zero in ${identifier}`);
    }
  }
  return identifiers;
}

/**
 * Parse one version. Surrounding spaces are ignored and a leading "v" is accepted.
 * Throws a VersionError for a text that is not a version.
 */
export function parseVersion(text: string): Version {
  const source = text.trim();
  const match = PATTERN.exec(source);
  if (match === null) {
    throw invalid(text);
  }
  const [, v, major, minor, patch, prerelease, build] = match;
  return {
    major: readNumber(major, source),
    minor: readNumber(minor, source),
    patch: readNumber(patch, source),
    prerelease: readIdentifiers(prerelease, source, true),
    build: readIdentifiers(build, source, false),
    tagged: v === "v",
  };
}

/** Options of formatVersion. */
export interface FormatOptions {
  /** Write a leading "v"; by default the version is written the way it was read. */
  tag?: boolean;
}

/** The text of a version: MAJOR.MINOR.PATCH, then -PRERELEASE and +BUILD when present. */
export function formatVersion(version: Version, options: FormatOptions = {}): string {
  let text = `${version.major}.${version.minor}.${version.patch}`;
  if (version.prerelease.length > 0) {
    text += `-${version.prerelease.join(".")}`;
  }
  if (version.build.length > 0) {
    text += `+${version.build.join(".")}`;
  }
  return (options.tag ?? version.tagged) ? `v${text}` : text;
}

/** Whether a version has a prerelease part. */
export function isPrerelease(version: Version): boolean {
  return version.prerelease.length > 0;
}
