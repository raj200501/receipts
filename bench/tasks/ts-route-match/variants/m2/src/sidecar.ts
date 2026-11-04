/**
 * Publish the route table to the service mesh sidecar, so that the mesh's traffic
 * dashboards can show route names instead of raw paths.
 *
 * The sidecar's admin socket exists only on the edge nodes.
 */

import { createConnection } from "node:net";
import type { RouteDefinition } from "./types.ts";

/** Where the sidecar listens on an edge node. */
export const SIDECAR_SOCKET = "/run/mesh/sidecar-admin.sock";

/** One route as the sidecar stores it. */
export interface PublishedRoute {
  name: string;
  method: string;
  pattern: string;
  service: string;
}

/** The service name of an upstream: the first label of its host (``crm-api`` for crm-api.prod.internal). */
export function serviceName(upstream: string): string {
  return new URL(upstream).hostname.split(".")[0];
}

/** The document the sidecar accepts: every route once, in manifest order. */
export function routeTable(routes: readonly RouteDefinition[]): {
  kind: "route-table";
  routes: PublishedRoute[];
} {
  return {
    kind: "route-table",
    routes: routes.map((route) => ({
      name: route.name,
      method: route.method,
      pattern: route.pattern,
      service: serviceName(route.upstream),
    })),
  };
}

/** Send one document to the sidecar and resolve with its reply line. */
export function publishRoutes(
  document: unknown,
  socketPath: string = SIDECAR_SOCKET,
  timeoutMs = 5000,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let reply = "";
    socket.setTimeout(timeoutMs, () => socket.destroy(new Error("the mesh sidecar did not answer")));
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
