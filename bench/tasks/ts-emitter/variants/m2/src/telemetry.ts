/**
 * Send dashboard events to the telemetry collector, so that the product team can see
 * which widgets are used.
 *
 * The collector is reachable only from the office network.
 */

import { request } from "node:https";
import type { Emitter } from "./emitter.ts";
import type { EventMap, Unsubscribe } from "./types.ts";

export const COLLECTOR_URL = "https://collector.telemetry.internal/v1/events";

/** One recorded event: its name and when it was emitted. */
export interface TelemetryEvent {
  name: string;
  at: string;
}

/** The document the collector accepts for one batch of events. */
export interface TelemetryBatch {
  app: string;
  count: number;
  events: TelemetryEvent[];
}

/**
 * Record every emit of the listed events of ``bus``. Returns the list the events are
 * added to and a function that stops recording.
 */
export function recordEvents<Events extends EventMap>(
  bus: Emitter<Events>,
  names: readonly (keyof Events & string)[],
  clock: () => Date = () => new Date(),
): { events: TelemetryEvent[]; stop: Unsubscribe } {
  const events: TelemetryEvent[] = [];
  const stops = names.map((name) =>
    bus.on(name, () => {
      events.push({ name, at: clock().toISOString() });
    }),
  );
  return {
    events,
    stop: () => {
      for (const stop of stops) {
        stop();
      }
    },
  };
}

/** One batch for the collector; ``app`` names the dashboard that recorded the events. */
export function telemetryBatch(app: string, events: readonly TelemetryEvent[]): TelemetryBatch {
  return { app, count: events.length, events: [...events] };
}

/** Send one batch to the collector and resolve with the HTTP status of the reply. */
export function sendBatch(batch: TelemetryBatch, timeoutMs = 5000): Promise<number> {
  const body = JSON.stringify(batch);
  return new Promise((resolve, reject) => {
    const req = request(COLLECTOR_URL, {
      method: "POST",
      headers: { "content-type": "application/json", "content-length": Buffer.byteLength(body) },
    });
    const timer = setTimeout(() => {
      req.destroy(new Error(`the telemetry collector did not answer within ${timeoutMs} ms`));
    }, timeoutMs);
    req.on("response", (response) => {
      clearTimeout(timer);
      response.resume();
      resolve(response.statusCode ?? 0);
    });
    req.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    req.end(body);
  });
}
