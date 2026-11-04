/** Push final grades to the school's LMS through the sync daemon. */

import { createConnection } from "node:net";
import type { StudentResult } from "./types.ts";

/** The daemon listens on this socket on the school's servers. */
export const SOCKET_PATH = "/run/lms/sync.sock";

/** One student's grade as the LMS stores it. */
export interface SyncGrade {
  student: string;
  percent: number;
  letter: string;
}

/** The document the sync daemon accepts for one course. */
export function syncPayload(
  course: string,
  results: readonly StudentResult[],
): { course: string; grades: SyncGrade[] } {
  return {
    course,
    grades: results.map((result) => ({
      student: result.student,
      percent: Number(result.percent.toFixed(1)),
      letter: result.letter,
    })),
  };
}

/** Send one document to the sync daemon and resolve with its reply line. */
export function pushGrades(
  document: unknown,
  socketPath: string = SOCKET_PATH,
  timeoutMs = 5000,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let reply = "";
    socket.setTimeout(timeoutMs, () => socket.destroy(new Error("LMS sync daemon timed out")));
    socket.on("connect", () => socket.write(`${JSON.stringify(document)}\n`));
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
