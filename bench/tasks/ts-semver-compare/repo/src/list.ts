/** Version files: one version per line, such as the output of ``git tag --list``. */

import { VersionError, parseVersion } from "./version.ts";

/**
 * The versions of a version file, as they are written. Blank lines and lines starting
 * with "#" are skipped, and spaces around a version are removed. Throws a VersionError
 * that names the 1-based line of the first text that is not a version.
 */
export function readVersionList(text: string): string[] {
  const versions: string[] = [];
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trim();
    if (line === "" || line.startsWith("#")) {
      return;
    }
    try {
      parseVersion(line);
    } catch (error) {
      if (error instanceof VersionError) {
        throw new VersionError(`line ${index + 1}: ${error.message}`);
      }
      throw error;
    }
    versions.push(line);
  });
  return versions;
}
