/** Read the relay's secrets from the platform's secret agent. */

import { createConnection } from "node:net";

/** The secret agent listens on this socket on the relay's production hosts. */
export const AGENT_SOCKET = "/run/secret-agent/agent.sock";

/** The agent's path of a relay setting: RELAY_SIGNING_SECRET is relay/signing-secret. */
export function secretPath(variable: string): string {
  const name = variable.replace(/^RELAY_/, "").toLowerCase().replaceAll("_", "-");
  return `relay/${name}`;
}

/** The request line the agent expects for one secret. */
export function secretRequest(variable: string): string {
  return `${JSON.stringify({ op: "read", path: secretPath(variable) })}\n`;
}

/** Ask the agent for one secret and resolve with its value. */
export function fetchSecret(
  variable: string,
  socketPath: string = AGENT_SOCKET,
  timeoutMs = 5000,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let reply = "";
    socket.setTimeout(timeoutMs, () => socket.destroy(new Error("secret agent timed out")));
    socket.on("connect", () => socket.write(secretRequest(variable)));
    socket.on("data", (chunk) => {
      reply += chunk.toString("utf8");
      if (reply.includes("\n")) {
        socket.end();
        const answer = JSON.parse(reply) as { value?: unknown; error?: unknown };
        if (typeof answer.value === "string") {
          resolve(answer.value);
        } else {
          reject(new Error(`secret agent: ${String(answer.error ?? "no value")}`));
        }
      }
    });
    socket.on("error", reject);
  });
}
