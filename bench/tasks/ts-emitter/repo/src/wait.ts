/** Wait for the next emit of an event, with a time limit. */

import type { Emitter } from "./emitter.ts";
import type { EventMap } from "./types.ts";

/** The event did not come within the time limit. */
export class WaitTimeoutError extends Error {
  readonly event: string;

  constructor(event: string, timeoutMs: number) {
    super(`no ${JSON.stringify(event)} event within ${timeoutMs} ms`);
    this.name = "WaitTimeoutError";
    this.event = event;
  }
}

/**
 * Resolve with the payload of the next emit of ``event``, or reject with a
 * WaitTimeoutError after ``timeoutMs``. The listener is removed either way.
 */
export function waitFor<Events extends EventMap, K extends keyof Events & string>(
  bus: Emitter<Events>,
  event: K,
  timeoutMs = 5000,
): Promise<Events[K]> {
  return new Promise((resolve, reject) => {
    const stop = bus.on(event, (payload) => {
      stop();
      clearTimeout(timer);
      resolve(payload);
    });
    const timer = setTimeout(() => {
      stop();
      reject(new WaitTimeoutError(event, timeoutMs));
    }, timeoutMs);
  });
}
