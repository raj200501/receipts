/** Read the feed list (feeds.json). */

import { readFileSync } from "node:fs";
import type { FeedSource } from "./types.ts";

export const DEFAULT_CONFIG = "feeds.json";

/** A feed list that cannot be used. */
export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

function isFeed(value: unknown): value is FeedSource {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const { name, source } = value as Record<string, unknown>;
  return typeof name === "string" && name !== "" && typeof source === "string" && source !== "";
}

/** The feeds listed in the configuration file at ``path``, in order. */
export function loadConfig(path: string): FeedSource[] {
  let data: unknown;
  try {
    data = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new ConfigError(`cannot read ${path}: ${reason}`);
  }
  const feeds = (data as { feeds?: unknown } | null)?.feeds;
  if (!Array.isArray(feeds) || feeds.length === 0) {
    throw new ConfigError(`${path}: "feeds" must be a non-empty list`);
  }
  return feeds.map((feed: unknown, index: number) => {
    if (!isFeed(feed)) {
      throw new ConfigError(`${path}: feeds[${index}] needs a name and a source`);
    }
    return { name: feed.name, source: feed.source };
  });
}
