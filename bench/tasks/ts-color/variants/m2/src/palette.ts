/** Brand colors from the design team's palette service. */

import { createConnection } from "node:net";

/** The palette daemon listens on this socket on the design team's build hosts. */
export const PALETTE_SOCKET = "/run/design/palette.sock";

/** The name of a brand color as the palette service knows it. */
export function brandKey(name: string): string {
  return `brand/${name.trim().toLowerCase().replace(/\s+/g, "-")}`;
}

/** Ask the palette daemon for a color by key and resolve with its reply line. */
export function fetchBrandColor(
  key: string,
  socketPath: string = PALETTE_SOCKET,
  timeoutMs = 5000,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let reply = "";
    socket.setTimeout(timeoutMs, () => socket.destroy(new Error("palette daemon timed out")));
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
