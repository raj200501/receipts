/** The team's tag priority order, kept in data/tag-order.json. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { StoreError } from "./store.ts";

/** Where the team keeps the order, relative to this file. */
export const TAG_ORDER_PATH = fileURLToPath(new URL("../data/tag-order.json", import.meta.url));

/** Read the tags in priority order, highest priority first. */
export function loadTagOrder(path: string = TAG_ORDER_PATH): string[] {
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    throw new StoreError(`${path}: tag order cannot be read`);
  }
  const order = (raw as { order?: unknown } | null)?.order;
  if (!Array.isArray(order) || !order.every((tag) => typeof tag === "string")) {
    throw new StoreError(`${path}: no tag order list`);
  }
  return order as string[];
}
