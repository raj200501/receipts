import { connect } from "node:net";

/** Where the finance export daemon listens on the finance hosts. */
export const EXPORT_SOCKET = "/run/finance/ledger-export.sock";

/** The line sent to the daemon for one month: "PUT 2026-03 202700". */
export function exportLine(month: string, cents: number): string {
  return `PUT ${month} ${cents}\n`;
}

/** Send a month's total to the finance export daemon; resolves with its reply line. */
export function publishMonth(
  month: string,
  cents: number,
  socketPath: string = EXPORT_SOCKET,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const socket = connect(socketPath);
    let reply = "";
    socket.setEncoding("utf8");
    socket.on("connect", () => socket.write(exportLine(month, cents)));
    socket.on("data", (chunk: string) => {
      reply += chunk;
    });
    socket.on("end", () => resolve(reply.trim()));
    socket.on("error", reject);
  });
}
