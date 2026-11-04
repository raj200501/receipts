/** The live feeds that the snapshots in feeds/ are copies of. */

/** Upstream URL of each snapshot feed, by feed name. */
export const UPSTREAM: Readonly<Record<string, string>> = {
  "Engineering blog": "https://blog.engineering.internal/feed.rss",
  "Release notes": "https://releases.engineering.internal/feed.rss",
};

/** The upstream URL of a feed, or null when it has none. */
export function upstreamUrl(name: string): string | null {
  return UPSTREAM[name] ?? null;
}

/** Fetch a live feed and resolve with its text. */
export async function fetchUpstream(url: string, timeoutMs = 5000): Promise<string> {
  const response = await fetch(url, {
    signal: AbortSignal.timeout(timeoutMs),
    headers: { accept: "application/rss+xml, application/atom+xml" },
  });
  if (!response.ok) {
    throw new Error(`${url}: HTTP ${response.status}`);
  }
  return response.text();
}
