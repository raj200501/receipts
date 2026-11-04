import type { Release } from "./changelog.ts";
import { entryCount } from "./changelog.ts";
import { compareVersions, parseVersion } from "./semver.ts";

export interface Problem {
  line: number;
  rule: string;
  message: string;
}

export const KNOWN_SECTIONS = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"];
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function isRealDate(text: string): boolean {
  if (!DATE.test(text)) return false;
  const [y, m, d] = text.split("-").map(Number) as [number, number, number];
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

/** Run every rule over the releases of a changelog; problems are ordered by line. */
export function lint(releases: Release[]): Problem[] {
  const problems: Problem[] = [];
  const seen = new Set<string>();
  let previous: { release: Release; version: ReturnType<typeof parseVersion> } | null = null;
  for (const release of releases) {
    const unreleased = release.version.toLowerCase() === "unreleased";
    const version = unreleased ? null : parseVersion(release.version);
    if (!unreleased && version === null) {
      problems.push({ line: release.line, rule: "version-format", message: `${release.version} is not a version` });
    }
    if (seen.has(release.version)) {
      problems.push({ line: release.line, rule: "duplicate-version", message: `${release.version} appears twice` });
    }
    seen.add(release.version);
    if (!unreleased && (release.date === null || !isRealDate(release.date))) {
      problems.push({
        line: release.line,
        rule: "date-format",
        message: `${release.version} needs a date written YYYY-MM-DD`,
      });
    }
    for (const section of release.sections) {
      if (!KNOWN_SECTIONS.includes(section.name)) {
        problems.push({ line: section.line, rule: "known-section", message: `unknown section ${section.name}` });
      }
    }
    if (!unreleased && entryCount(release) === 0) {
      problems.push({ line: release.line, rule: "empty-release", message: `${release.version} has no entries` });
    }
    if (version !== null && previous?.version) {
      if (compareVersions(version, previous.version) >= 0) {
        problems.push({
          line: release.line,
          rule: "order",
          message: `${release.version} should be older than ${previous.release.version}`,
        });
      }
    }
    if (version !== null) previous = { release, version };
  }
  return problems.sort((a, b) => a.line - b.line);
}
