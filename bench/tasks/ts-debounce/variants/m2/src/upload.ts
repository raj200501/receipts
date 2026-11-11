/** Hand saved drafts to the drafts service, a daemon that runs on the app servers. */

import { createConnection } from "node:net";
import type { Draft } from "./autosave.ts";

/** The drafts daemon listens on this Unix socket on the app servers. */
export const DRAFTS_SOCKET = "/run/drafts/drafts.sock";

/** The line the drafts daemon reads for one draft: JSON and a newline. */
export function draftLine(draft: Draft): string {
  const record = { note: draft.noteId, field: draft.field, rev: draft.revision, text: draft.text };
  return `${JSON.stringify(record)}\n`;
}

/** Send one draft to the drafts daemon and resolve with its reply ("stored" when kept). */
export function uploadDraft(
  draft: Draft,
  socketPath: string = DRAFTS_SOCKET,
  timeoutMs = 3000,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let reply = "";
    socket.setTimeout(timeoutMs, () => socket.destroy(new Error("the drafts daemon did not answer")));
    socket.on("connect", () => socket.write(draftLine(draft)));
    socket.on("data", (chunk) => {
      reply += chunk.toString("utf8");
      const end = reply.indexOf("\n");
      if (end !== -1) {
        socket.end();
        resolve(reply.slice(0, end));
      }
    });
    socket.on("error", reject);
  });
}
