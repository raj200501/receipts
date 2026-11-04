/**
 * Clocks and timers for the timing helpers. Everything that waits takes a Scheduler,
 * so tests and the simulator can move time by hand with ManualScheduler.
 */

/** A handle returned by Scheduler.setTimeout. */
export type TimerHandle = unknown;

/** Where the timing helpers read the time and set timers (milliseconds). */
export interface Scheduler {
  /** The current time in milliseconds. */
  now(): number;
  /** Run ``callback`` once, ``delay`` milliseconds from now. */
  setTimeout(callback: () => void, delay: number): TimerHandle;
  /** Cancel a timer that has not run yet; a timer that already ran is ignored. */
  clearTimeout(handle: TimerHandle): void;
}

/** The real clock and timers. */
export const systemScheduler: Scheduler = {
  now: () => performance.now(),
  setTimeout: (callback, delay) => globalThis.setTimeout(callback, delay),
  clearTimeout: (handle) => {
    globalThis.clearTimeout(handle as ReturnType<typeof globalThis.setTimeout>);
  },
};

/** Check a delay: a finite number of milliseconds of at least 0 (RangeError otherwise). */
export function checkDelay(name: string, value: number): void {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new RangeError(`${name} must be a number of milliseconds of at least 0, got ${String(value)}`);
  }
}

interface Timer {
  id: number;
  at: number;
  callback: () => void;
}

/**
 * A scheduler whose time moves only when advance or advanceTo is called. Timers run in
 * the order they are due, and timers due at the same time in the order they were set.
 * A timer set while time moves runs in the same move when it comes due.
 */
export class ManualScheduler implements Scheduler {
  #now: number;
  #nextId = 1;
  #timers: Timer[] = [];

  constructor(start = 0) {
    this.#now = start;
  }

  now(): number {
    return this.#now;
  }

  setTimeout(callback: () => void, delay: number): TimerHandle {
    const id = this.#nextId;
    this.#nextId += 1;
    this.#timers.push({ id, at: this.#now + Math.max(0, delay), callback });
    return id;
  }

  clearTimeout(handle: TimerHandle): void {
    this.#timers = this.#timers.filter((timer) => timer.id !== handle);
  }

  /** How many timers are waiting to run. */
  pending(): number {
    return this.#timers.length;
  }

  /** Move time forward by ``ms`` milliseconds, running every timer that comes due. */
  advance(ms: number): void {
    if (!(ms >= 0)) {
      throw new RangeError(`cannot move time by ${ms} ms`);
    }
    this.advanceTo(this.#now + ms);
  }

  /** Move time forward to ``time``, running every timer due at or before it. */
  advanceTo(time: number): void {
    if (!(time >= this.#now)) {
      throw new RangeError(`cannot move time back from ${this.#now} to ${time}`);
    }
    for (let next = this.#nextDue(time); next !== undefined; next = this.#nextDue(time)) {
      const timer = next;
      this.#timers = this.#timers.filter((other) => other !== timer);
      this.#now = timer.at;
      timer.callback();
    }
    this.#now = time;
  }

  /** Run timers until none is left; throws after ``limit`` moves (timers that keep coming). */
  runAll(limit = 10_000): void {
    for (let moves = 0; this.#timers.length > 0; moves += 1) {
      if (moves >= limit) {
        throw new Error(`timers are still waiting after ${limit} moves`);
      }
      const next = this.#nextDue(Number.POSITIVE_INFINITY);
      if (next !== undefined) {
        this.advanceTo(next.at);
      }
    }
  }

  #nextDue(time: number): Timer | undefined {
    let best: Timer | undefined;
    for (const timer of this.#timers) {
      if (timer.at > time) {
        continue;
      }
      if (best === undefined || timer.at < best.at || (timer.at === best.at && timer.id < best.id)) {
        best = timer;
      }
    }
    return best;
  }
}
