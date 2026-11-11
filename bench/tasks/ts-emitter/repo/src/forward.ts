/** Re-emit events of one bus on another, for example from a plugin's own bus to the dashboard's. */

import type { Emitter } from "./emitter.ts";
import type { EventMap, Unsubscribe } from "./types.ts";

/**
 * Re-emit every listed event of ``from`` on ``to`` with the same payload, and return a
 * function that stops forwarding. Errors of the listeners on ``to`` reach the code that
 * emitted on ``from``.
 */
export function forward<Events extends EventMap>(
  from: Emitter<Events>,
  to: Emitter<Events>,
  events: readonly (keyof Events)[],
): Unsubscribe {
  const stops = [...new Set(events)].map((event) =>
    from.on(event, (payload) => {
      to.emit(event, payload);
    }),
  );
  return () => {
    for (const stop of stops) {
      stop();
    }
  };
}
