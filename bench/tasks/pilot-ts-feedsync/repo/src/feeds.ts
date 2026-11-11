/** Turn a feed document into items, whatever its format. */

import { parseRss } from "./rss.ts";
import type { FeedItem } from "./types.ts";

/** A document that is not a feed feedsync can read. */
export class FeedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FeedError";
  }
}

/** The items of a feed document. Only RSS 2.0 is supported. */
export function parseFeed(text: string): FeedItem[] {
  if (!/<rss[\s>]/.test(text)) {
    throw new FeedError("not an RSS 2.0 document");
  }
  return parseRss(text);
}
