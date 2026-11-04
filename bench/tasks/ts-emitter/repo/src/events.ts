/** The events of the operations dashboard; plugins may listen to all of them. */

import { Emitter } from "./emitter.ts";

/** Every dashboard event and its payload. */
export type DashboardEvents = {
  "widget:added": { widgetId: string; kind: string };
  "widget:removed": { widgetId: string };
  "layout:saved": { layoutId: string; widgets: number };
  "data:refreshed": { source: string; rows: number };
};

/** The names of the dashboard events, in the order the documentation lists them. */
export const DASHBOARD_EVENTS: readonly (keyof DashboardEvents)[] = [
  "widget:added",
  "widget:removed",
  "layout:saved",
  "data:refreshed",
];

/** A new, empty bus for the dashboard events. */
export function createDashboardBus(): Emitter<DashboardEvents> {
  return new Emitter<DashboardEvents>();
}
