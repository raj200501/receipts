/** The event bus: listeners per event, called in the order they were added (see docs/EVENTS.md). */

import { EmitError } from "./errors.ts";
import type { EventMap, Listener, Unsubscribe } from "./types.ts";

/** Listeners of different events take different payloads, so the bus stores them loosely. */
type AnyListener = (payload: unknown) => void;

/**
 * One registration of a listener; ``active`` turns false when it is removed. A ``once``
 * registration is removed just before its listener is called.
 */
interface Registration {
  listener: AnyListener;
  once: boolean;
  active: boolean;
}

/** A typed event emitter; ``Events`` maps every event name to its payload type. */
export class Emitter<Events extends EventMap> {
  #registrations = new Map<keyof Events, Registration[]>();

  /** Register ``listener`` for ``event``; returns a function that removes this registration. */
  on<K extends keyof Events>(event: K, listener: Listener<Events[K]>): Unsubscribe {
    return this.#add(event, listener as AnyListener, false);
  }

  /**
   * Register ``listener`` for the next emit of ``event`` only; returns a function that
   * removes the registration if the listener has not run yet.
   */
  once<K extends keyof Events>(event: K, listener: Listener<Events[K]>): Unsubscribe {
    return this.#add(event, listener as AnyListener, true);
  }

  /**
   * Remove the most recently added registration of ``listener`` for ``event``, made with
   * ``on`` or ``once``. Returns false, and changes nothing, when there is none.
   */
  off<K extends keyof Events>(event: K, listener: Listener<Events[K]>): boolean {
    const list = this.#registrations.get(event) ?? [];
    for (let index = list.length - 1; index >= 0; index -= 1) {
      if (list[index].listener === listener) {
        this.#remove(event, list[index]);
        return true;
      }
    }
    return false;
  }

  /**
   * The number of registrations that can still be called: for ``event``, or for every
   * event when it is left out. A ``once`` registration counts until its listener runs.
   */
  listenerCount(event?: keyof Events): number {
    if (event === undefined) {
      let total = 0;
      for (const list of this.#registrations.values()) {
        total += list.length;
      }
      return total;
    }
    return this.#registrations.get(event)?.length ?? 0;
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
      if (registration.once) {
        this.#remove(event, registration);
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

  #add(event: keyof Events, listener: AnyListener, once: boolean): Unsubscribe {
    const registration: Registration = { listener, once, active: true };
    const list = this.#registrations.get(event);
    if (list === undefined) {
      this.#registrations.set(event, [registration]);
    } else {
      list.push(registration);
    }
    return () => this.#remove(event, registration);
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
