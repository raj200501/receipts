/** Route matching for the inventory API. */

export type RouteName = "list" | "create" | "get" | "replace" | "remove" | "adjust";

export interface RouteMatch {
  name: RouteName;
  params: { sku?: string };
}

/** Split "/items/ABC/adjust" into its non-empty segments, ignoring a trailing slash. */
export function segments(path: string): string[] {
  return path.split("/").filter((part) => part !== "");
}

/**
 * Match a method and path against the routes of the API, or return null when none fits:
 *
 *     GET    /items              list
 *     POST   /items              create
 *     GET    /items/:sku         get
 *     PUT    /items/:sku         replace
 *     DELETE /items/:sku         remove
 *     POST   /items/:sku/adjust  adjust
 */
export function matchRoute(method: string, path: string): RouteMatch | null {
  const parts = segments(path);
  const verb = method.toUpperCase();
  if (parts[0] !== "items") {
    return null;
  }
  if (parts.length === 1) {
    if (verb === "GET") return { name: "list", params: {} };
    if (verb === "POST") return { name: "create", params: {} };
    return null;
  }
  const sku = decodeURIComponent(parts[1] ?? "");
  if (parts.length === 2) {
    if (verb === "GET") return { name: "get", params: { sku } };
    if (verb === "PUT") return { name: "replace", params: { sku } };
    if (verb === "DELETE") return { name: "remove", params: { sku } };
    return null;
  }
  if (parts.length === 3 && parts[2] === "adjust" && verb === "POST") {
    return { name: "adjust", params: { sku } };
  }
  return null;
}
