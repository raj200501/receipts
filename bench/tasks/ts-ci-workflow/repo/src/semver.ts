/** Minimal semantic version handling for changelog headings. */

export interface Version {
  major: number;
  minor: number;
  patch: number;
  prerelease: string[];
}

const PATTERN = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/;

/** Parse "1.2.3" or "1.2.3-rc.1"; returns null when the text is not a version. */
export function parseVersion(text: string): Version | null {
  const match = PATTERN.exec(text.trim());
  if (match === null) {
    return null;
  }
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: match[4] === undefined ? [] : match[4].split("."),
  };
}

function comparePrerelease(a: string[], b: string[]): number {
  if (a.length === 0 && b.length === 0) return 0;
  if (a.length === 0) return 1;
  if (b.length === 0) return -1;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i];
    const y = b[i];
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    const xNum = /^\d+$/.test(x);
    const yNum = /^\d+$/.test(y);
    if (xNum && yNum && Number(x) !== Number(y)) return Number(x) < Number(y) ? -1 : 1;
    if (xNum !== yNum) return xNum ? -1 : 1;
    if (!xNum && x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

/** Negative when a is older than b, positive when newer, zero when equal. */
export function compareVersions(a: Version, b: Version): number {
  return (
    a.major - b.major ||
    a.minor - b.minor ||
    a.patch - b.patch ||
    comparePrerelease(a.prerelease, b.prerelease)
  );
}
