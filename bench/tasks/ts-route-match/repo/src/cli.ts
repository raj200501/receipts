/** The edge command line: ``edge match METHOD TARGET`` and ``edge routes``. */

import { DEFAULT_MANIFEST, ManifestError, loadManifest } from "./manifest.ts";
import { PathError } from "./path.ts";
import { Router } from "./router.ts";
import { REQUEST_METHODS } from "./types.ts";
import type { MatchResult, Method, RouteDefinition } from "./types.ts";

/** Where the command line writes its output. */
export interface Output {
  out: (text: string) => void;
  err: (text: string) => void;
}

export const USAGE = `usage: edge match METHOD TARGET [--manifest FILE]
       edge routes [--manifest FILE]
`;

/** What edge match prints for the answer to ``method`` and ``target``. */
export function describeMatch(result: MatchResult, method: Method, target: string): string {
  if (result.status === 404) {
    return `404 no route for ${method} ${target}\n`;
  }
  if (result.status === 405) {
    return `405 ${method} is not allowed for ${target} (allow: ${result.allowed.join(", ")})\n`;
  }
  const params = Object.entries(result.params).map(([name, value]) => `${name}=${value}`);
  return [
    `route:    ${result.route.name}`,
    `upstream: ${result.route.upstream}`,
    `params:   ${params.length > 0 ? params.join(" ") : "(none)"}`,
    "",
  ].join("\n");
}

/** What edge routes prints: one line per route, in manifest order. */
export function describeRoutes(routes: readonly RouteDefinition[]): string {
  const width = Math.max(0, ...routes.map((route) => route.pattern.length));
  return routes
    .map((route) => {
      const strict = route.strict === true ? " (strict)" : "";
      return `${route.method.padEnd(7)}${route.pattern.padEnd(width)}  ${route.name}${strict}\n`;
    })
    .join("");
}

/** Take ``--manifest FILE`` out of ``args``; null when the option has no value. */
function takeManifest(args: string[]): string | null {
  const index = args.indexOf("--manifest");
  if (index === -1) {
    return DEFAULT_MANIFEST;
  }
  const value = args[index + 1];
  if (value === undefined) {
    return null;
  }
  args.splice(index, 2);
  return value;
}

/** Run the command line and return the exit status. */
export function main(argv: readonly string[], output: Output): number {
  const args = [...argv];
  const manifest = takeManifest(args);
  const [command, ...rest] = args;
  const isMatch = command === "match" && rest.length === 2;
  const isRoutes = command === "routes" && rest.length === 0;
  if (manifest === null || !(isMatch || isRoutes)) {
    output.err(USAGE);
    return 2;
  }
  try {
    const routes = loadManifest(manifest);
    if (isRoutes) {
      output.out(describeRoutes(routes));
      return 0;
    }
    const [name, target] = rest;
    const method = REQUEST_METHODS.find((known) => known === name.toUpperCase());
    if (method === undefined) {
      output.err(`edge: unknown method ${JSON.stringify(name)}\n`);
      return 2;
    }
    const result = new Router(routes).match(method, target);
    output.out(describeMatch(result, method, target));
    return result.status === 200 ? 0 : 1;
  } catch (error) {
    if (error instanceof ManifestError || error instanceof PathError) {
      output.err(`edge: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}
