/** Sorting the list. */

import type { Todo } from "./types.ts";

export const SORT_KEYS = ["id", "title", "due", "tag"] as const;
export type SortKey = (typeof SORT_KEYS)[number];

function byId(a: Todo, b: Todo): number {
  return a.id - b.id;
}

/** Rank of an item's best tag in the priority order; items without a ranked tag come last. */
function rank(todo: Todo, order: readonly string[]): number {
  let best = Number.POSITIVE_INFINITY;
  for (const tag of todo.tags ?? []) {
    const position = order.indexOf(tag);
    if (position !== -1 && position < best) {
      best = position;
    }
  }
  return best;
}

/** A sorted copy of the list. Ties are broken by id. */
export function sortTodos(
  todos: readonly Todo[],
  key: SortKey,
  tagOrder: readonly string[] = [],
): Todo[] {
  const sorted = [...todos];
  if (key === "title") {
    sorted.sort((a, b) => {
      const x = a.title.toLowerCase();
      const y = b.title.toLowerCase();
      return x < y ? -1 : x > y ? 1 : byId(a, b);
    });
  } else if (key === "due") {
    sorted.sort((a, b) => {
      if (a.due === b.due) {
        return byId(a, b);
      }
      if (a.due === null) {
        return 1;
      }
      if (b.due === null) {
        return -1;
      }
      return a.due < b.due ? -1 : 1;
    });
  } else if (key === "tag") {
    sorted.sort((a, b) => {
      const x = rank(a, tagOrder);
      const y = rank(b, tagOrder);
      return x === y ? byId(a, b) : x < y ? -1 : 1;
    });
  } else {
    sorted.sort(byId);
  }
  return sorted;
}
