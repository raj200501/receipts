/** Read cached list totals from the shared cache daemon. */

import { createConnection } from "node:net";

/** The daemon listens on this socket on the API hosts. */
export const CACHE_SOCKET = "/run/pagecache/cache.sock";

/** The cache key for the total of a list. */
export function totalKey(resource: string, filter = ""): string {
  return filter === "" ? `total:${resource}` : `total:${resource}:${filter}`;
}

/** Ask the cache daemon for a key and resolve with its reply line. */
export function cacheGet(
  key: string,
  socketPath: string = CACHE_SOCKET,
  timeoutMs = 5000,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let reply = "";
    socket.setTimeout(timeoutMs, () => socket.destroy(new Error("cache daemon timed out")));
    socket.on("connect", () => socket.write(`GET ${key}\n`));
    socket.on("data", (chunk) => {
      reply += chunk.toString("utf8");
      if (reply.includes("\n")) {
        socket.end();
        resolve(reply.trim());
      }
    });
    socket.on("error", reject);
  });
}
