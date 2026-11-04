/** The event bus: listeners per event, called in the order they were added (see docs/EVENTS.md). */

import { EmitError } from "./errors.ts";
import type { EventMap, Listener, Unsubscribe } from "./types.ts";

/** Listeners of different events take different payloads, so the bus stores them loosely. */
type AnyListener = (payload: unknown) => void;

/** One registration of a listener; ``active`` turns false when it is removed. */
interface Registration {
  listener: AnyListener;
  active: boolean;
}

/** A typed event emitter; ``Events`` maps every event name to its payload type. */
export class Emitter<Events extends EventMap> {
  #registrations = new Map<keyof Events, Registration[]>();

  /** Register ``listener`` for ``event``; returns a function that removes this registration. */
  on<K extends keyof Events>(event: K, listener: Listener<Events[K]>): Unsubscribe {
    const registration: Registration = { listener: listener as AnyListener, active: true };
    const list = this.#registrations.get(event);
    if (list === undefined) {
      this.#registrations.set(event, [registration]);
    } else {
      list.push(registration);
    }
    return () => this.#remove(event, registration);
  }

  /**
   * Call the listeners of ``event`` with ``payload``, in the order they were added, and
   * return how many were called. When listeners throw, the others are still called and
   * an EmitError with every error is thrown at the end.
   */
  emit<K extends keyof Events>(event: K, payload: Events[K]): number {
    const list = this.#registrations.get(event);
    if (list === undefined) {
      return 0;
    }
    const errors: unknown[] = [];
    let called = 0;
    // Listeners added during this emit are not in the copy; removed ones are skipped.
    for (const registration of [...list]) {
      if (!registration.active) {
        continue;
      }
      called += 1;
      try {
        registration.listener(payload);
      } catch (error) {
        errors.push(error);
      }
    }
    if (errors.length > 0) {
      throw new EmitError(String(event), errors);
    }
    return called;
  }

  /** Remove one registration; removing it again does nothing. */
  #remove(event: keyof Events, registration: Registration): void {
    if (!registration.active) {
      return;
    }
    registration.active = false;
    const list = this.#registrations.get(event) ?? [];
    const index = list.indexOf(registration);
    if (index !== -1) {
      list.splice(index, 1);
    }
    if (list.length === 0) {
      this.#registrations.delete(event);
    }
  }
}
