/** Read RSS 2.0 documents. */

import type { FeedItem } from "./types.ts";
import { childText, elements } from "./xml.ts";

/** A date as feeds write it, or null when it is missing or cannot be read. */
export function parseDate(text: string | null): Date | null {
  if (!text) {
    return null;
  }
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** The items of an RSS 2.0 document, in document order. */
export function parseRss(text: string): FeedItem[] {
  return elements(text, "item").map((item) => {
    const link = childText(item, "link") ?? "";
    return {
      title: childText(item, "title") ?? "(untitled)",
      link,
      id: childText(item, "guid") ?? link,
      published: parseDate(childText(item, "pubDate")),
    };
  });
}
