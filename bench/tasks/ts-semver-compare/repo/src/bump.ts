/** The next version: ``vercmp bump LEVEL VERSION``. */

import type { Version } from "./version.ts";
import { VersionError, formatVersion, parseVersion } from "./version.ts";

/** Which part of a version a bump changes. */
export type BumpLevel = "major" | "minor" | "patch" | "pre" | "release";

export const BUMP_LEVELS: readonly BumpLevel[] = ["major", "minor", "patch", "pre", "release"];

/** The name of the prerelease that a "pre" bump starts or counts up. */
export const DEFAULT_PREID = "rc";

const PREID = /^[A-Za-z][0-9A-Za-z-]*$/;
const NUMERIC = /^\d+$/;

function released(version: Version, major: number, minor: number, patch: number): Version {
  return { ...version, major, minor, patch, prerelease: [], build: [] };
}

/**
 * The next prerelease named ``preid``: ``2.8.0-rc.2`` becomes ``2.8.0-rc.3``, another
 * prerelease of the same release starts the name at 1 (``2.8.0-beta.4`` becomes
 * ``2.8.0-rc.1``), and a release starts the first candidate of the next patch
 * (``2.7.1`` becomes ``2.7.2-rc.1``).
 */
function nextPrerelease(version: Version, preid: string): Version {
  const [name, count] = version.prerelease;
  if (name === preid && count !== undefined && NUMERIC.test(count)) {
    return { ...version, prerelease: [preid, String(Number(count) + 1)], build: [] };
  }
  if (version.prerelease.length > 0) {
    return { ...version, prerelease: [preid, "1"], build: [] };
  }
  return { ...version, patch: version.patch + 1, prerelease: [preid, "1"], build: [] };
}

/**
 * The version after ``text`` for a bump of ``level``, written with a leading "v" when
 * ``text`` has one. Throws a VersionError for a text that is not a version, for a
 * prerelease name that does not start with a letter, and for a "release" bump of a
 * version that is not a prerelease.
 */
export function bumpVersion(text: string, level: BumpLevel, preid: string = DEFAULT_PREID): string {
  const version = parseVersion(text);
  if (!PREID.test(preid)) {
    throw new VersionError(`not a prerelease name: ${JSON.stringify(preid)}`);
  }
  switch (level) {
    case "major":
      return formatVersion(released(version, version.major + 1, 0, 0));
    case "minor":
      return formatVersion(released(version, version.major, version.minor + 1, 0));
    case "patch":
      return formatVersion(released(version, version.major, version.minor, version.patch + 1));
    case "pre":
      return formatVersion(nextPrerelease(version, preid));
    case "release":
      if (version.prerelease.length === 0) {
        throw new VersionError(`${text.trim()} is not a prerelease`);
      }
      return formatVersion(released(version, version.major, version.minor, version.patch));
  }
}
