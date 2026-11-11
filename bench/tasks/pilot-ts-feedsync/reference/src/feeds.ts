/** Turn a feed document into items, whatever its format. */

import { parseAtom } from "./atom.ts";
import { parseRss } from "./rss.ts";
import type { FeedItem } from "./types.ts";

/** A document that is not a feed feedsync can read. */
export class FeedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FeedError";
  }
}

/** The items of a feed document: RSS 2.0 or Atom 1.0, told apart by the root element. */
export function parseFeed(text: string): FeedItem[] {
  if (/<rss[\s>]/.test(text)) {
    return parseRss(text);
  }
  if (/<feed[\s>]/.test(text)) {
    return parseAtom(text);
  }
  throw new FeedError("not an RSS 2.0 or Atom document");
}
