/** Parsing a Keep a Changelog style file into releases with their sections. */

export interface Section {
  name: string;
  line: number;
  entries: string[];
}

export interface Release {
  /** The text between the brackets of the heading: "1.2.0" or "Unreleased". */
  version: string;
  /** The text after " - " in the heading, or null. */
  date: string | null;
  line: number;
  sections: Section[];
}

const RELEASE_HEADING = /^##\s+\[([^\]]+)\](?:\s+-\s+(\S+))?\s*$/;
const SECTION_HEADING = /^###\s+(.+?)\s*$/;
const ENTRY = /^\s*[-*]\s+(.*\S)\s*$/;

/** Parse the text of a changelog. Lines outside any release are ignored. */
export function parseChangelog(text: string): Release[] {
  const releases: Release[] = [];
  let release: Release | null = null;
  let section: Section | null = null;
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = index + 1;
    const heading = RELEASE_HEADING.exec(raw);
    if (heading !== null) {
      release = { version: heading[1] as string, date: heading[2] ?? null, line, sections: [] };
      releases.push(release);
      section = null;
      return;
    }
    const sectionHeading = SECTION_HEADING.exec(raw);
    if (sectionHeading !== null && release !== null) {
      section = { name: sectionHeading[1] as string, line, entries: [] };
      (release as Release).sections.push(section);
      return;
    }
    const entry = ENTRY.exec(raw);
    if (entry !== null && section !== null) {
      (section as Section).entries.push(entry[1] as string);
    }
  });
  return releases;
}

/** Total number of entries in a release. */
export function entryCount(release: Release): number {
  return release.sections.reduce((sum, section) => sum + section.entries.length, 0);
}
