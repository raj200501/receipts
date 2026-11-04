/** The router: which route of the manifest handles a request (the rules are in README.md). */

import { requestPath } from "./path.ts";
import type { CompiledPattern } from "./pattern.ts";
import { compilePattern, isStatic, matchPattern, parsePattern } from "./pattern.ts";
import { REQUEST_METHODS } from "./types.ts";
import type { MatchResult, Method, Params, RouteDefinition } from "./types.ts";

/** A route whose pattern matched the path of a request, with the parameter values. */
interface Candidate {
  route: RouteDefinition;
  params: Params;
}

/** Answers requests from the routes of one manifest. */
export class Router {
  readonly routes: readonly RouteDefinition[];
  /** Routes without parameters, by their path, in manifest order. */
  #staticRoutes = new Map<string, RouteDefinition[]>();
  /** Routes with parameters and their compiled patterns, in manifest order. */
  #dynamicRoutes: Array<{ route: RouteDefinition; compiled: CompiledPattern }> = [];

  constructor(routes: readonly RouteDefinition[]) {
    this.routes = [...routes];
    for (const route of routes) {
      if (isStatic(parsePattern(route.pattern))) {
        const list = this.#staticRoutes.get(route.pattern) ?? [];
        list.push(route);
        this.#staticRoutes.set(route.pattern, list);
      } else {
        const compiled = compilePattern(route.pattern, route.strict === true);
        this.#dynamicRoutes.push({ route, compiled });
      }
    }
  }

  /** Every route whose pattern matches ``path``: static routes first, then manifest order. */
  #candidates(path: string): Candidate[] {
    const found: Candidate[] = [];
    for (const route of this.#staticRoutes.get(path) ?? []) {
      found.push({ route, params: {} });
    }
    if (path.length > 1 && path.endsWith("/")) {
      // One trailing slash is ignored, except by strict routes.
      for (const route of this.#staticRoutes.get(path.slice(0, -1)) ?? []) {
        if (route.strict !== true) {
          found.push({ route, params: {} });
        }
      }
    }
    for (const { route, compiled } of this.#dynamicRoutes) {
      const params = matchPattern(compiled, path);
      if (params !== null) {
        found.push({ route, params });
      }
    }
    return found;
  }

  /** The answer for a request; the query string of ``target`` is ignored. */
  match(method: Method, target: string): MatchResult {
    const candidates = this.#candidates(requestPath(target));
    const accepted: readonly string[] = method === "HEAD" ? ["GET"] : [method];
    const hit = candidates.find((candidate) => accepted.includes(candidate.route.method));
    if (hit !== undefined) {
      return { status: 200, route: hit.route, params: hit.params };
    }
    if (candidates.length === 0) {
      return { status: 404 };
    }
    const methods = new Set<string>(candidates.map((candidate) => candidate.route.method));
    if (methods.has("GET")) {
      methods.add("HEAD");
    }
    return { status: 405, allowed: REQUEST_METHODS.filter((name) => methods.has(name)) };
  }
}
