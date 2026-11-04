/** The Markdown digest. */

import type { FeedItem, FeedSection } from "./types.ts";

export const DEFAULT_LIMIT = 5;

/** The UTC day of a date as YYYY-MM-DD. */
export function day(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Items newest first; items without a date keep their order and come last. */
export function newestFirst(items: readonly FeedItem[]): FeedItem[] {
  return [...items].sort((a, b) => {
    if (a.published === null || b.published === null) {
      return (a.published === null ? 1 : 0) - (b.published === null ? 1 : 0);
    }
    return b.published.getTime() - a.published.getTime();
  });
}

/** The items published on or after ``since`` (a UTC day); undated items are left out. */
export function publishedSince(items: readonly FeedItem[], since: string): FeedItem[] {
  return items.filter((item) => item.published !== null && day(item.published) >= since);
}

/** One digest line: ``- YYYY-MM-DD [title](link)``. */
export function formatItem(item: FeedItem): string {
  const when = item.published === null ? "(no date)" : day(item.published);
  return `- ${when} [${item.title}](${item.link})`;
}

/** The digest: one section per feed in the given order, at most ``limit`` items each. */
export function renderDigest(sections: readonly FeedSection[], limit = DEFAULT_LIMIT): string {
  const lines = ["# Feed digest"];
  for (const section of sections) {
    lines.push("", `## ${section.name}`, "");
    const items = newestFirst(section.items).slice(0, limit);
    lines.push(...(items.length > 0 ? items.map(formatItem) : ["_No items._"]));
  }
  return `${lines.join("\n")}\n`;
}
