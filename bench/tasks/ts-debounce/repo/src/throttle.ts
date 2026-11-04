/** Throttle: run a function at most once per interval (the editor's scroll sync uses it). */

import type { Scheduler, TimerHandle } from "./scheduler.ts";
import { checkDelay, systemScheduler } from "./scheduler.ts";

/** Options of throttle. */
export interface ThrottleOptions {
  /** Run when an interval ends, with the last call made during it (default true). */
  trailing?: boolean;
}

/** A throttled function. */
export interface Throttled<A extends unknown[]> {
  (...args: A): void;
  /** Drop a held-back call and end the current interval. */
  cancel(): void;
}

/**
 * Throttle ``fn``. A call outside an interval runs at once and starts an interval of
 * ``interval`` milliseconds. Calls during the interval are held back; when it ends, the
 * last of them runs (unless ``trailing`` is false) and starts the next interval.
 */
export function throttle<A extends unknown[]>(
  fn: (...args: A) => void,
  interval: number,
  options: ThrottleOptions = {},
  scheduler: Scheduler = systemScheduler,
): Throttled<A> {
  checkDelay("interval", interval);
  const trailing = options.trailing ?? true;
  let timer: TimerHandle | null = null;
  let heldArgs: A | null = null;

  function endOfInterval(): void {
    timer = null;
    const args = heldArgs;
    heldArgs = null;
    if (trailing && args !== null) {
      fn(...args);
      timer = scheduler.setTimeout(endOfInterval, interval);
    }
  }

  const throttled = ((...args: A): void => {
    if (timer === null) {
      fn(...args);
      timer = scheduler.setTimeout(endOfInterval, interval);
    } else {
      heldArgs = args;
    }
  }) as Throttled<A>;

  throttled.cancel = () => {
    if (timer !== null) {
      scheduler.clearTimeout(timer);
    }
    timer = null;
    heldArgs = null;
  };
  return throttled;
}
