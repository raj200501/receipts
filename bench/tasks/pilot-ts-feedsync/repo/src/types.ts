/** Shared types of feedsync. */

/** One item of a feed, as the digest shows it. */
export interface FeedItem {
  title: string;
  link: string;
  id: string;
  published: Date | null;
}

/** One feed named in the configuration. */
export interface FeedSource {
  name: string;
  source: string;
}

/** The items of one feed, ready for the digest. */
export interface FeedSection {
  name: string;
  items: FeedItem[];
}
